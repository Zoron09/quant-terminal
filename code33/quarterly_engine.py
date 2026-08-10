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

# Appended to the local-dataset-miss series_flag. Kept as a module constant so
# pipeline._fill_gaps can recognise exactly this case (and only this case) when it
# refines the message with the SEC-side answer — matching on a shared constant
# rather than on a hand-copied substring that could silently drift apart.
_LOCAL_MISS_HINT = (" - the bulk dataset is built from XBRL financial statements, "
                    "so a filer publishing none can never appear in it")

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


# Which point sources are eligible for restatement detection.
#
# A derived Q4 was excluded until 2026-08-09, on the stated reasoning that "a derived
# value already combines multiple filings, so there's no single figure to check". That
# describes the point's OWN provenance, which this query never uses: it asks whether some
# LATER filing published a discrete qtrs=1 figure for the same ddate, and a derived point
# carries both fields that needs — .adsh (the 10-K it was back-solved from) and .tag (the
# FY tag). Measured across all 606 tickers, the exclusion was missing 27 tickers / 37
# quarters, including JNJ (Kenvue), DD (Qnity), CALY (Topgolf), ADEA (Xperi), PBI (GEC)
# and MAGN (the Magnera reverse merger). 30 of the 37 later figures come from a 10-K
# comparative, not a fiscal-calendar change, so this is not a niche of odd filers.
#
# 'edgartools' is still absent, and NOT by choice: pipeline._fill_gaps constructs those
# points AFTER get_quarterly_series has already run this function, so they are never
# offered to it at all. That gap hits the NEWEST quarters — the ones inside the scoring
# window — and is deliberately left for its own investigation. See bug_report.md.
_RESTATEMENT_ELIGIBLE_SOURCES = ("reported", "derived_fy_minus_quarters")


def _is_annual_mistagged_as_quarter(row, num_q4: pd.DataFrame) -> bool:
    """True when a candidate 'quarterly' row is really the filer's ANNUAL figure wearing a
    90-day period.

    A real defect in SEC data, not a hypothetical. HF Sinclair's FY2025 10-K tags
    $28,580,000,000 for 2024-10-01..2024-12-31 as qtrs=1 — bit-identical to the qtrs=4
    fact for 2024-01-01..2024-12-31 in the SAME filing. Accepting that as a restatement
    replaces DINO's correct derived Q4 ($6.5B) with an annual number and drags a quarter
    that is INSIDE the 4-rate scoring window from -0.55% to -77.38%.

    A fiscal year ends on the same date as its own Q4, so the annual fact shares the
    quarter's ddate. The test is therefore exact equality of value within one accession —
    an INPUT check, deliberately NOT a size heuristic. A magnitude threshold is the
    mistake the +/-1000% margin guard already taught (see bug_report.md): it cannot tell
    a mis-tag from a real corporate action, and real restatements here run from 0.01% to
    206% in BOTH directions.

    Applies to every candidate, not just derived ones: a mis-tagged annual figure is not a
    valid restatement for a reported point either, and gating it by source would be
    arbitrary. Proven non-regressive — across all 606 tickers, zero reported points change
    their flag or value under this guard.
    """
    twin = num_q4[
        (num_q4["adsh"] == row["adsh"])
        & (num_q4["ddate"] == row["ddate"])
        & (num_q4["tag"] == row["tag"])
    ]
    return bool((twin["value"] == row["value"]).any())


def _attach_restatement_flags(
    points: List[QuarterPoint], num_df: pd.DataFrame, sub_df: pd.DataFrame,
    num_q4: pd.DataFrame
) -> None:
    """For each point whose source is in _RESTATEMENT_ELIGIBLE_SOURCES, looks for a row in
    num_df matching the same (ddate, qtrs=1, tag) but a DIFFERENT adsh — num_df is
    already sliced to this company's own pulled filings and already filtered to
    segments=='' by the caller's filter chain. Candidates that are really an annual
    figure mis-tagged as a quarter are dropped first (see
    _is_annual_mistagged_as_quarter). Of what survives, takes the one from whichever
    filing was filed latest; if its value differs from the point's own, sets
    restated=True and restated_value to that later figure. Purely additive — never
    touches the primary `value`, same principle as .plausible.

    This catches cases like 3M/Solventum: a divestiture reclassifies prior-period
    revenue/NI to continuing-operations-only in later filings' comparative columns,
    without ever changing what the original filing itself reported for its own period.

    The tag match is EXACT and load-bearing. Relaxing it to "any tag in the priority list"
    surfaces 7 more apparent restatements across the universe, and all 7 are cross-CONCEPT
    comparisons rather than revisions — NetIncomeLoss vs ProfitLoss (NCI-inclusive, the
    AES case), Revenues vs RevenueFromContractWithCustomer... (DLTR -42.6%, SON -18.3%).
    Do not loosen it.
    """
    filed_by_adsh = sub_df["filed"] if "filed" in sub_df.columns else None

    for point in points:
        if (point.source not in _RESTATEMENT_ELIGIBLE_SOURCES
                or point.value is None or point.tag is None):
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

        # Drop mis-tagged annual figures BEFORE picking the latest, not after: such a row
        # is not a weaker observation, it is not an observation of this quarter at all, so
        # a genuine earlier restatement behind it must still be able to win.
        candidates = candidates[~candidates.apply(
            lambda r: _is_annual_mistagged_as_quarter(r, num_q4), axis=1)]
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
        # Three very different causes reach this line and used to report one
        # generic message, which is how XOM's July-2026 holdco reorg looked
        # identical to a Greek shipping company that has never filed a 10-Q.
        # Re-query without the form filter to tell them apart. This restores the
        # signal `check_cik_discontinuity` provided in tools/preflight_checks.py
        # before the 2026-07-22 engine swap deleted it, but reports it inline on
        # the failing path rather than as a separate preflight pass.
        #
        # The "no 10-Q/10-K filings found" prefix is deliberate: api/server.py's
        # _classify_failure buckets on that substring, so scan grouping is
        # unchanged and only the detail after the dash is new.
        try:
            any_reports = reader.get_all_company_reports()
        except Exception:
            any_reports = []

        if not any_reports:
            # PRECISION MATTERS HERE. CompanyIndexReader reads the LOCAL
            # secfsdstools parquet mirror, so an empty result means "absent from
            # the local dataset", NOT "this company never filed". The old wording
            # claimed the latter and then pointed at PREDECESSOR_CIK as though a
            # holdco reorg were the likely cause — a red herring that sends anyone
            # debugging it after a corporate action that did not happen.
            # Confirmed on PBT (Permian Basin Royalty Trust): 118 real 10-Q/10-K
            # filings at SEC going back to 1995, yet reported here as having none.
            # Its actual disqualifier is that it publishes no XBRL financial data
            # at all (companyfacts returns HTTP 404) — the bulk dataset is built
            # from XBRL financial statements, so such filers can never appear in
            # it. Same for the closed-end funds BSTZ/RMT/HQH/HQL, which file
            # N-CSR/NPORT-P instead of 10-Q/10-K.
            # pipeline._fill_gaps appends which of those two cases this actually
            # is, since only it has the ticker needed to ask SEC.
            detail = ("no filings for this CIK in the local dataset" + _LOCAL_MISS_HINT)
        else:
            forms = sorted({r.form for r in any_reports})
            detail = (f"CIK files {'/'.join(forms[:4])} but no 10-Q/10-K - annual-only "
                      f"foreign private issuer or non-operating registrant")

        return QuarterlyRevenueSeries(
            cik=cik, points=[], series_flag=f"no 10-Q/10-K filings found - {detail}")

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
    _attach_restatement_flags(points, num_df, sub_df, num_q4)

    return QuarterlyRevenueSeries(cik=cik, points=points[:quarters])
