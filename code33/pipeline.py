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

from code33.edgar_fill import MATCH_TOLERANCE_DAYS, fetch_discrete_quarter
from code33.models import QuarterlyNetMarginSeries, QuarterlyRevenueSeries, QuarterPoint
from code33.net_margin import NI_TAGS, _is_implausible_net_income, pair_margin_series
from code33.quarterly_engine import get_quarterly_series
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


def _fill_gaps(
    ticker: str,
    series: QuarterlyRevenueSeries,
    tag_priority: List[str],
    quarters: int,
) -> QuarterlyRevenueSeries:
    if series.series_flag is not None and not series.points:
        return series

    usable_ends = [p.period_end for p in series.points if p.value is not None]
    all_ends = [p.period_end for p in series.points]
    expected = expected_quarter_ends(all_ends, quarters)

    missing = [
        target for target in expected
        if not any(abs((target - have).days) <= MATCH_TOLERANCE_DAYS for have in usable_ends)
    ]

    filled: List[QuarterPoint] = []
    for target in missing:
        hit = fetch_discrete_quarter(ticker, target, tag_priority)
        if hit is None:
            log.info("pipeline: %s quarter ~%s missing from both sources", ticker, target)
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
