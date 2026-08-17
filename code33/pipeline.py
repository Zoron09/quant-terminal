"""Completeness layer: secfsdstools-primary series with targeted live-EDGAR gap fill.

Order of operations (fixed by design):
  1. The ticker's fiscal cadence comes from secfsdstools' own filing history —
     never from a live call.
  2. From today's date + that cadence, compute which `quarters` quarter-ends
     should exist (per-ticker pattern, not generic calendar quarters — this is
     what makes Jan-31-FYE retailers like WMT come out right).
  3. Check which of those secfsdstools actually has.
  4. Fill only the genuine gaps from edgartools (edgar_fill) — fallback source
     only, never wholesale. Usually, but not necessarily, the newest quarter.
"""
import logging
from datetime import date, timedelta
from typing import Callable, List, Optional

from code33.edgar_fill import (
    MATCH_TOLERANCE_DAYS,
    fetch_derived_fy_quarter,
    fetch_discrete_quarter,
    has_xbrl_quarterly_facts,
)
from code33.models import QuarterlyNetMarginSeries, QuarterlyRevenueSeries, QuarterPoint
from code33.net_margin import NI_TAGS, _is_implausible_net_income, pair_margin_series
from code33.quarterly_engine import _LOCAL_MISS_HINT, get_quarterly_series
from code33.revenue import REVENUE_TAGS, _is_implausible_revenue
from code33.ticker_lookup import resolve_ticker_to_cik

log = logging.getLogger(__name__)

# The SEC 10-Q deadline: 40 days for large-accelerated/accelerated filers, 45 for
# non-accelerated and smaller reporting companies. This is the LATEST a quarter can
# legally appear. Reference only — deliberately NOT used to gate anything, see below.
SEC_10Q_DEADLINE_DAYS = 45

# When a projected quarter becomes worth ASKING for. This is a different question
# from the deadline above, and using the deadline for it hid real, already-public
# quarters. Measured across 17,635 10-Qs in this universe (local filing index):
# 96.6% are filed BEFORE day 45, median 36 days, fastest observed 9 days (DAL).
# 494 of 499 companies had their most recent 10-Q filed inside the old 45-day gate,
# so nearly every company carried a blind window every quarter — ICE's was 15 days
# (filed 2026-07-30, invisible until 2026-08-14).
# Set below the fastest observed filer: a projection that finds nothing costs one
# filter over an already-cached facts frame and adds NO point (fetch_discrete_quarter
# returns None -> continue), so it cannot corrupt output for any filer.
PROJECTION_MIN_AGE_DAYS = 10


QUARTER_STEP_DAYS = 91


def expected_quarter_ends(
    known_ends: List[date], quarters: int, today: Optional[date] = None
) -> List[date]:
    """The `quarters` quarter-end dates that should exist as of today, newest
    first: the ticker's own known historical ends, plus ~91-day forward
    projections from the latest known end for quarters that should be filed
    by now but haven't reached the bulk mirror yet. Backward dates are never
    arithmetically projected — quarter lengths aren't uniform (COST's Q4 runs
    16 weeks), so projecting backward past real known ends manufactured
    false gaps that then double-filled quarters under slightly different
    dates. Forward projection drift is absorbed by MATCH_TOLERANCE_DAYS."""
    if not known_ends:
        return []
    today = today or date.today()
    cutoff = today - timedelta(days=PROJECTION_MIN_AGE_DAYS)

    known_sorted = sorted(set(known_ends), reverse=True)
    anchor = known_sorted[0]

    projections: List[date] = []
    candidate = anchor + timedelta(days=QUARTER_STEP_DAYS)
    while candidate <= cutoff:
        projections.append(candidate)
        candidate += timedelta(days=QUARTER_STEP_DAYS)
    projections.sort(reverse=True)

    # Projections are ADDITIVE, never displacing known ends. The old form,
    # `(projections + known_sorted)[:quarters]`, let each projection evict the
    # OLDEST known end from the fill window — and an evicted end whose value is
    # None is a real gap that then silently stops being back-filled. Those oldest
    # quarters are the year-ago YoY bases (the adapter pulls n_quarters + 4 for
    # exactly that reason), so losing them corrupts YoY rather than just trimming
    # history. Harmless to return a longer list: `expected` only drives fill
    # ATTEMPTS in _fill_gaps, it never determines output length.
    return projections + known_sorted[:quarters]


def _explain_local_dataset_miss(
    ticker: str, series: QuarterlyRevenueSeries
) -> QuarterlyRevenueSeries:
    """Adds the SEC-side half of the diagnosis to a local-dataset miss.

    quarterly_engine can only report what it checked — the local secfsdstools
    mirror — because it works from a CIK and never sees the ticker. Whether SEC
    holds any XBRL for the company is the other half, and it decides whether a
    predecessor-CIK hunt is even worth starting. Only that one flag is touched;
    every other series_flag (20-F filers, CIK-resolution failures) is returned
    byte-identical.
    """
    if _LOCAL_MISS_HINT not in (series.series_flag or ""):
        return series
    try:
        has_xbrl = has_xbrl_quarterly_facts(ticker)
    except Exception:  # diagnosis must never become a new failure mode
        return series
    extra = (" - SEC HAS XBRL quarterly facts for this ticker, so the local "
             "dataset is the gap: check whether a corporate reorganization moved "
             "it to a new CIK (see PREDECESSOR_CIK in ticker_lookup.py)"
             if has_xbrl else
             " - SEC has no XBRL quarterly facts for this ticker either, so there "
             "is nothing to recover: not a missing-data bug")
    return QuarterlyRevenueSeries(
        cik=series.cik, points=[], series_flag=series.series_flag + extra)


def _fill_gaps(
    ticker: str,
    series: QuarterlyRevenueSeries,
    tag_priority: List[str],
    quarters: int,
) -> QuarterlyRevenueSeries:
    if series.series_flag is not None and not series.points:
        return _explain_local_dataset_miss(ticker, series)

    usable_ends = [p.period_end for p in series.points if p.value is not None]
    all_ends = [p.period_end for p in series.points]
    expected = expected_quarter_ends(all_ends, quarters)

    missing = [
        target for target in expected
        if not any(abs((target - have).days) <= MATCH_TOLERANCE_DAYS for have in usable_ends)
    ]

    # Median of the values already established for this ticker, handed to the fill
    # as a scale reference so a units-mismatched candidate can be skipped in favour
    # of the next tag. None when nothing is established yet, which disables the
    # guard entirely — see fetch_discrete_quarter's SCALE GUARD note.
    known_values = sorted(abs(p.value) for p in series.points if p.value)
    reference_magnitude = (known_values[len(known_values) // 2]
                           if known_values else None)

    filled: List[QuarterPoint] = []
    for target in missing:
        hit = fetch_discrete_quarter(ticker, target, tag_priority, reference_magnitude)
        if hit is None:
            # No discrete quarter exists for this target. Before giving up, try
            # deriving it as FY - (Q1+Q2+Q3): most filers never publish a
            # discrete Q4 at all, so for a fiscal year end this is not a missing
            # figure, it is one that has to be back-solved. The bulk path already
            # does exactly this; until now the live path did not, which left the
            # year-end quarter absent for as long as the 10-K took to reach the
            # bulk mirror — months, for a non-December filer.
            #
            # Deliberately SECOND: a real reported Q4 always wins, same ordering
            # as the bulk path, and this only ever runs on a quarter that would
            # otherwise have been logged as missing.
            derived = fetch_derived_fy_quarter(
                ticker, target, tag_priority, reference_magnitude)
            if derived is None:
                log.info("pipeline: %s quarter ~%s missing from both sources", ticker, target)
                continue
            (period_end, value, tag, accession, filing_date, fy, fp,
             derived_from) = derived
            filled.append(
                QuarterPoint(
                    period_end=period_end,
                    filed=filing_date,
                    adsh=accession,
                    # The 10-K is genuinely where this figure comes from, and the
                    # bulk path labels its own derived Q4s the same way.
                    form="10-K",
                    fy=fy,
                    fp=fp,
                    value=value,
                    tag=tag,
                    # Distinct from both 'edgartools' (a real discrete quarter
                    # pulled live) and 'derived_fy_minus_quarters' (the bulk
                    # path's own arithmetic). Naming it separately is not only
                    # provenance: it also keeps this point OUT of
                    # _RESTATEMENT_ELIGIBLE_SOURCES and out of
                    # _attach_plausibility's derived-only branch, neither of
                    # which has run by this point in the pipeline. Reusing the
                    # bulk path's string would have silently claimed checks that
                    # never happened.
                    source="derived_edgartools_fy_minus_quarters",
                    derived_from_adsh=derived_from,
                    # EXPLICIT, and explicitly not computed. The restatement
                    # flagger runs inside get_quarterly_series, which returned
                    # before this function was called, so no filled point can
                    # carry a computed flag. Same known limitation recorded for
                    # `edgartools` fills on 2026-08-10; stated here rather than
                    # left to the dataclass default so it cannot be mistaken for
                    # a checked result.
                    restated=False,
                    restated_value=None,
                )
            )
            log.info(
                "pipeline: %s quarter %s DERIVED from 10-K %s minus quarters %s (%s)",
                ticker, period_end, accession, derived_from, tag)
            continue
        period_end, value, tag, accession, filing_date, fy, fp = hit
        filled.append(
            QuarterPoint(
                period_end=period_end,
                filed=filing_date,
                adsh=accession,
                form="10-Q",
                fy=fy,
                fp=fp,
                value=value,
                tag=tag,
                source="edgartools",
            )
        )
        log.info("pipeline: %s quarter %s filled from edgartools (%s)", ticker, period_end, tag)

    if not filled:
        return series

    # An edgar fill never overrides a secfsdstools value — drop any placeholder
    # 'missing' point the fill supersedes, then merge.
    merged = [
        p for p in series.points
        if not (
            p.value is None
            and any(abs((p.period_end - f.period_end).days) <= MATCH_TOLERANCE_DAYS for f in filled)
        )
    ]
    merged.extend(filled)
    merged.sort(key=lambda p: p.period_end, reverse=True)
    return QuarterlyRevenueSeries(cik=series.cik, points=merged[:quarters])


def get_complete_revenue_series(ticker: str, quarters: int = 8) -> QuarterlyRevenueSeries:
    cik = resolve_ticker_to_cik(ticker)
    if cik is None:
        return QuarterlyRevenueSeries(cik=0, points=[], series_flag=f"{ticker}: could not resolve to a CIK")
    base = get_quarterly_series(cik, REVENUE_TAGS, _is_implausible_revenue, quarters)
    return _fill_gaps(ticker, base, REVENUE_TAGS, quarters)


def get_complete_net_income_series(ticker: str, quarters: int = 8) -> QuarterlyRevenueSeries:
    cik = resolve_ticker_to_cik(ticker)
    if cik is None:
        return QuarterlyRevenueSeries(cik=0, points=[], series_flag=f"{ticker}: could not resolve to a CIK")
    base = get_quarterly_series(cik, NI_TAGS, _is_implausible_net_income, quarters)
    return _fill_gaps(ticker, base, NI_TAGS, quarters)


def get_complete_net_margin(ticker: str, quarters: int = 8) -> QuarterlyNetMarginSeries:
    revenue_series = get_complete_revenue_series(ticker, quarters)
    ni_series = get_complete_net_income_series(ticker, quarters)
    cik = revenue_series.cik or ni_series.cik
    return pair_margin_series(revenue_series, ni_series, cik, quarters)
