"""Shared machinery for pulling a company's own sequential discrete-quarter figures
(revenue, net income, ...) from SEC filings: datapath-cached quarter reads, Q4/FY
derivation via date-window fiscal-year matching (not self-reported fy/fp DEI tags,
which some companies tag inconsistently between their 10-K and its own 10-Qs), and
plausibility flagging. Domain modules (revenue.py, net_margin.py) supply their own
tag priority list and plausibility rule; everything else here is tag-agnostic.
"""
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from secfsdstools.c_index.companyindexreading import CompanyIndexReader
from secfsdstools.c_index.indexdataaccess import IndexReport
from secfsdstools.d_container.databagmodel import RawDataBag
from secfsdstools.e_filter.rawfiltering import (
    MainCoregRawFilter,
    NoSegmentInfoRawFilter,
    OfficialTagsOnlyRawFilter,
    USDOnlyRawFilter,
)

from code33.models import QuarterPoint, QuarterlyRevenueSeries

FORMS = ["10-Q", "10-K"]

# Companies file ~4 reports/year (10-K + three 10-Qs). The history window is sized off
# `quarters`, not hardcoded, so it always covers the oldest requested quarter's fiscal
# year plus HISTORY_MARGIN_YEARS extra years of buffer for Q4-derivation siblings and
# irregular filing cadence.
FILINGS_PER_YEAR = 4
HISTORY_MARGIN_YEARS = 2


# Process-wide cache, keyed by the underlying quarter-file datapath (e.g. a report's
# fullPath such as .../quarter/2025q4.zip) rather than by ticker. SEC quarterly source
# files hold every company's filings for that quarter, so two different tickers whose
# reports land in the same quarter file can reuse one already-loaded read. Each cached
# entry holds ALL companies' rows for that datapath (tag-filtered, not adsh-filtered) so
# it stays reusable across tickers; callers slice down to their own adshs afterward.
# Keyed by (datapath, tuple(sorted(tag_filter))) since revenue and net-income pulls use
# different tag lists against the same datapaths.
_DATAPATH_CACHE: Dict[Tuple[str, Tuple[str, ...]], RawDataBag] = {}

# pre.txt.parquet is never read: nothing downstream consumes pre_df (the raw filters
# that reference it only use it to build a pre_df result that's discarded), so this
# empty stub with the real column set is enough to keep filter chaining working.
_EMPTY_PRE_DF = pd.DataFrame(columns=["adsh", "report", "line", "stmt", "inpth", "rfile", "tag", "version", "plabel", "negating"])


def _read_datapath_bag(datapath: str, tag_filter: List[str]) -> RawDataBag:
    sub_df = pd.read_parquet(os.path.join(datapath, "sub.txt.parquet"))
    num_df = pd.read_parquet(
        os.path.join(datapath, "num.txt.parquet"), filters=[("tag", "in", tag_filter)]
    )
    num_df.loc[num_df.coreg.isna(), "coreg"] = ""
    num_df.loc[num_df.segments.isna(), "segments"] = ""
    return RawDataBag.create(sub_df=sub_df, pre_df=_EMPTY_PRE_DF, num_df=num_df)


def _collect_with_datapath_cache(
    index_reports: List[IndexReport], tag_filter: List[str]
) -> RawDataBag:
    cache_key_tags = tuple(sorted(tag_filter))
    reports_by_datapath: Dict[str, List[IndexReport]] = defaultdict(list)
    for report in index_reports:
        reports_by_datapath[report.fullPath].append(report)

    partial_bags: List[RawDataBag] = []
    for datapath, reports in reports_by_datapath.items():
        cache_key = (datapath, cache_key_tags)
        cached = _DATAPATH_CACHE.get(cache_key)
        if cached is None:
            cached = _read_datapath_bag(datapath, tag_filter)
            _DATAPATH_CACHE[cache_key] = cached

        adshs = [r.adsh for r in reports]
        partial_bags.append(
            RawDataBag.create(
                sub_df=cached.sub_df[cached.sub_df["adsh"].isin(adshs)],
                pre_df=cached.pre_df,
                num_df=cached.num_df[cached.num_df["adsh"].isin(adshs)],
            )
        )

    return RawDataBag.concat(partial_bags)


def _int_to_date(value: int) -> date:
    s = str(int(value))
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _dedupe_reports(index_reports: List[IndexReport]) -> List[IndexReport]:
    """Keeps one report per adsh; the index can list the same adsh from overlapping
    quarterly source zips."""
    seen = {report.adsh: report for report in index_reports}
    return list(seen.values())


def _best_tag_value(rows: pd.DataFrame, tag_priority: List[str]) -> Tuple[Optional[float], Optional[str]]:
    """Given num_df rows already sliced to one (adsh, ddate, qtrs) combination, picks the
    highest-priority tag (in the caller's tag_priority order) that carries a value."""
    for tag in tag_priority:
        tag_rows = rows[rows["tag"] == tag]
        if not tag_rows.empty and pd.notna(tag_rows.iloc[0]["value"]):
            return float(tag_rows.iloc[0]["value"]), tag
    return None, None


def _attach_plausibility(
    points: List[QuarterPoint], plausibility_check: Callable[[float, List[float]], bool]
) -> None:
    """Sets .plausible on derived Q4 points only, using sibling Q1/Q2/Q3 discrete values
    from the same fiscal year (whatever's available among the already-built points)."""
    by_fy: Dict[int, List[QuarterPoint]] = {}
    for point in points:
        if point.fy is not None:
            by_fy.setdefault(point.fy, []).append(point)

    for point in points:
        if point.source != "derived_fy_minus_quarters" or point.value is None or point.fy is None:
            continue
        siblings = [
            p.value
            for p in by_fy.get(point.fy, [])
            if p is not point and p.fp in ("Q1", "Q2", "Q3") and p.value is not None
        ]
        point.plausible = not plausibility_check(point.value, siblings)


def _attach_restatement_flags(
    points: List[QuarterPoint], num_df: pd.DataFrame, sub_df: pd.DataFrame
) -> None:
    """For each REPORTED point (not derived — a derived value already combines multiple
    filings, so there's no single figure to check for restatement), looks for a row in
    num_df matching the same (ddate, qtrs=1, tag) but a DIFFERENT adsh — num_df is
    already sliced to this company's own pulled filings and already filtered to
    segments=='' by the caller's filter chain. If one or more such rows exist, takes
    the one from whichever filing was filed latest; if its value differs from the
    point's own, sets restated=True and restated_value to that later figure. Purely
    additive — never touches the primary `value`, same principle as .plausible.

    This catches cases like 3M/Solventum: a divestiture reclassifies prior-period
    revenue/NI to continuing-operations-only in later filings' comparative columns,
    without ever changing what the original filing itself reported for its own period.
    """
    filed_by_adsh = sub_df["filed"] if "filed" in sub_df.columns else None

    for point in points:
        if point.source != "reported" or point.value is None or point.tag is None:
            continue

        ddate = int(point.period_end.strftime("%Y%m%d"))
        candidates = num_df[
            (num_df["ddate"] == ddate)
            & (num_df["qtrs"] == 1)
            & (num_df["tag"] == point.tag)
            & (num_df["adsh"] != point.adsh)
        ]
        if candidates.empty or filed_by_adsh is None:
            continue

        candidates = candidates.copy()
        candidates["_filed"] = candidates["adsh"].map(filed_by_adsh)
        candidates = candidates.dropna(subset=["_filed"])
        if candidates.empty:
            continue

        latest_row = candidates.sort_values("_filed").iloc[-1]
        restated_value = float(latest_row["value"])
        if restated_value != point.value:
            point.restated = True
            point.restated_value = restated_value


def get_quarterly_series(
    cik: int,
    tag_priority: List[str],
    plausibility_check: Callable[[float, List[float]], bool],
    quarters: int = 8,
) -> QuarterlyRevenueSeries:
    """A company's own sequential discrete-quarter figures for the given tag priority
    list, most recent first, with period end dates and per-point data-quality flags.
    Returns clean validated raw data only — no growth or ratio computation here.

    Most 10-Ks never carry a discrete ("three months ended") Q4 fact for the tag in
    question — they only report the full fiscal year (qtrs=4). For those, Q4 is
    derived as FY_total - (Q1 + Q2 + Q3), where the three quarters are whichever
    10-Qs' own period ends fall strictly between the previous 10-K's period end and
    this one's (the oldest 10-K in view falls back to a ~366-day window). This is
    deliberately date-based rather than keyed by each filing's self-reported
    `fy`/`fp` DEI tags: those tags are supposed to agree between a company's 10-K
    and its own same-year 10-Qs, but some companies (e.g. Dell, for several years)
    tag them inconsistently, which silently matched the wrong fiscal year's quarter
    under an fy-keyed approach. A handful of companies do disclose a real discrete
    Q4 fact directly; that reported figure always wins over the derived one.
    """

    reader = CompanyIndexReader.get_company_index_reader(cik=cik)
    index_reports = _dedupe_reports(reader.get_all_company_reports(forms=FORMS))

    if not index_reports:
        return QuarterlyRevenueSeries(cik=cik, points=[], series_flag="no 10-Q/10-K filings found")

    index_reports.sort(key=lambda r: r.period, reverse=True)

    # Only pull the recent slice of filing history the derivation actually needs —
    # CompanyReportCollector.get_company_collector() re-reads a cik's *entire* filing
    # history internally regardless of what's requested downstream, which is what made
    # this slow. Building the collector from an already-trimmed IndexReport list instead
    # skips loading everything older than the window.
    history_years = -(-quarters // FILINGS_PER_YEAR) + HISTORY_MARGIN_YEARS  # ceil
    history_window = history_years * FILINGS_PER_YEAR
    index_reports = index_reports[:history_window]

    databag = _collect_with_datapath_cache(index_reports=index_reports, tag_filter=tag_priority)
    databag = databag[OfficialTagsOnlyRawFilter()][USDOnlyRawFilter()][MainCoregRawFilter()][
        NoSegmentInfoRawFilter()
    ]

    num_df = databag.num_df.copy()
    num_df["value"] = pd.to_numeric(num_df["value"], errors="coerce")

    num_q1 = num_df[num_df["qtrs"] == 1]  # discrete "three months ended"
    num_q4 = num_df[num_df["qtrs"] == 4]  # full fiscal year

    sub_df = databag.sub_df.drop_duplicates(subset="adsh").set_index("adsh")

    def fy_fp_of(report: IndexReport) -> Tuple[Optional[int], Optional[str]]:
        if report.adsh not in sub_df.index:
            return None, None
        row = sub_df.loc[report.adsh]
        fy = int(row["fy"]) if pd.notna(row.get("fy")) else None
        fp = row.get("fp")
        return fy, fp

    # Discrete ("three months ended") value for every report, 10-K or 10-Q alike.
    # 10-Qs use this directly as their own reported figure; 10-Ks use it only to check
    # whether they happen to disclose a real discrete Q4 fact (rare, but wins if present).
    discrete_value_cache: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
    for report in index_reports:
        rows = num_q1[(num_q1["adsh"] == report.adsh) & (num_q1["ddate"] == report.period)]
        discrete_value_cache[report.adsh] = _best_tag_value(rows, tag_priority)

    # Date-window fiscal-year matching: for each 10-K, the quarters belonging to its
    # fiscal year are whichever 10-Qs' period end falls strictly between the previous
    # 10-K's period end and this one's — never based on any filing's self-reported
    # fy/fp tag, which can't be trusted to agree across a company's own filings.
    tenk_reports_asc = sorted((r for r in index_reports if r.form == "10-K"), key=lambda r: r.period)
    quarter_reports = [r for r in index_reports if r.form == "10-Q"]

    FALLBACK_WINDOW_DAYS = 366

    prev_10k_for: Dict[str, Optional[IndexReport]] = {}
    for i, r in enumerate(tenk_reports_asc):
        prev_10k_for[r.adsh] = tenk_reports_asc[i - 1] if i > 0 else None

    def quarters_in_fiscal_year(tenk_report: IndexReport) -> List[IndexReport]:
        this_end = _int_to_date(tenk_report.period)
        prev_10k = prev_10k_for.get(tenk_report.adsh)
        window_start = (
            _int_to_date(prev_10k.period) if prev_10k is not None
            else this_end - timedelta(days=FALLBACK_WINDOW_DAYS)
        )
        matched = [
            r for r in quarter_reports
            if window_start < _int_to_date(r.period) < this_end
        ]
        matched.sort(key=lambda r: r.period)
        return matched

    points: List[QuarterPoint] = []
    for report in index_reports:
        fy, fp = fy_fp_of(report)

        # 10-K fy labels can't be trusted either: WMT's own 10-Ks flip between
        # naming the fiscal year after its start year and its end year across
        # filings, while its 10-Qs are consistent (also mislabels plausibility
        # sibling grouping, which keys on fy). Relabel each 10-K from its
        # date-window-matched sibling 10-Qs' fy (majority vote), falling back
        # to the self-reported tag when no siblings are in view.
        if report.form == "10-K":
            sibling_fys = [
                fy_fp_of(q)[0] for q in quarters_in_fiscal_year(report)
            ]
            sibling_fys = [f for f in sibling_fys if f is not None]
            if sibling_fys:
                fy = max(set(sibling_fys), key=sibling_fys.count)

        value, tag = discrete_value_cache[report.adsh]
        source = "reported"
        derived_from_adsh: Optional[str] = None

        if value is None and report.form == "10-K":
            fy_rows = num_q4[(num_q4["adsh"] == report.adsh) & (num_q4["ddate"] == report.period)]
            fy_value, fy_tag = _best_tag_value(fy_rows, tag_priority)

            matched_quarters = quarters_in_fiscal_year(report)
            q_values = [discrete_value_cache[q.adsh][0] for q in matched_quarters]

            if (
                fy_value is not None
                and len(matched_quarters) == 3
                and all(v is not None for v in q_values)
            ):
                value = fy_value - sum(q_values)
                tag = fy_tag
                source = "derived_fy_minus_quarters"
                derived_from_adsh = ",".join(q.adsh for q in matched_quarters)
            else:
                source = "missing"

        elif value is None:
            source = "missing"

        points.append(
            QuarterPoint(
                period_end=_int_to_date(report.period),
                filed=_int_to_date(report.filed),
                adsh=report.adsh,
                form=report.form,
                fy=fy,
                fp=fp,
                value=value,
                tag=tag,
                source=source,
                derived_from_adsh=derived_from_adsh,
            )
        )

    _attach_plausibility(points, plausibility_check)
    _attach_restatement_flags(points, num_df, sub_df)

    return QuarterlyRevenueSeries(cik=cik, points=points[:quarters])
