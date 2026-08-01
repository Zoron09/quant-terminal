"""Pulls a company's own sequential discrete-quarter revenue figures from SEC filings.

Runnable directly for a manual eyeball check: python revenue.py AAPL MSFT
"""
import sys
from typing import List

from code33.models import QuarterlyRevenueSeries
from code33.quarterly_engine import get_quarterly_series
from code33.ticker_lookup import resolve_ticker_to_cik

# Priority-ordered revenue tags: first tag with a valid value wins.
# Mirrors the priority secfsdstools' own IncomeStatementStandardizer uses for 'Revenues'.
REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "RevenuesExcludingInterestAndDividends",
    # Banks (JPM et al.) report total net revenue under this tag and file none
    # of the tags above. Last priority — only ever fires when nothing else did.
    "RevenuesNetOfInterestExpense",
]


def _is_implausible_revenue(derived_value: float, sibling_values: List[float]) -> bool:
    """Flags a derived Q4 as implausible if negative, more than 4x the average of that
    fiscal year's other three quarters, or less than 25% of that average (catches a
    derivation that quietly grabbed the wrong fiscal year's quarters and produced a
    too-small result, which a ceiling-only check can't see). Never used to drop a
    value — caller still keeps it, just flagged."""
    if derived_value < 0:
        return True
    if not sibling_values:
        return False
    avg = sum(sibling_values) / len(sibling_values)
    if avg <= 0:
        return False
    if derived_value > 4 * avg:
        return True
    return derived_value < 0.25 * avg


def get_quarterly_revenue_series(cik: int, quarters: int = 8) -> QuarterlyRevenueSeries:
    """Company's own sequential discrete-quarter revenue figures, most recent first,
    with period end dates and a per-point data-quality source flag. Returns clean
    validated raw data only — no growth computation here.

    Most 10-Ks never carry a discrete ("three months ended") Q4 revenue fact — they
    only report the full fiscal year (qtrs=4). For those, Q4 is derived as
    FY_total - (Q1 + Q2 + Q3), where the three quarters are whichever 10-Qs' own
    period ends fall strictly between the previous 10-K's period end and this one's
    (the oldest 10-K in view falls back to a ~366-day window). This is deliberately
    date-based rather than keyed by each filing's self-reported `fy`/`fp` DEI tags:
    those tags are supposed to agree between a company's 10-K and its own same-year
    10-Qs, but some companies (e.g. Dell, for several years) tag them inconsistently,
    which silently matched the wrong fiscal year's quarter under an fy-keyed approach.
    A handful of companies do disclose a real discrete Q4 fact directly; that reported
    figure always wins over the derived one.
    """
    return get_quarterly_series(cik, REVENUE_TAGS, _is_implausible_revenue, quarters)


def _print_series_for_ticker(ticker: str) -> None:
    cik = resolve_ticker_to_cik(ticker)
    if cik is None:
        print(f"{ticker}: could not resolve to a CIK")
        return

    series = get_quarterly_revenue_series(cik)
    print(f"\n=== {ticker} (cik={cik}) ===")
    if not series.is_usable and not series.points:
        print(f"  UNUSABLE: {series.series_flag}")
        return

    header = (
        f"{'period_end':<12} {'form':<6} {'fy':<6} {'fp':<4} {'value':>18}  "
        f"{'source':<22} {'plausible':<9} tag / derived_from"
    )
    print(header)
    print("-" * len(header))
    for point in series.points:
        value_str = f"{point.value:,.0f}" if point.value is not None else "N/A"
        plausible_str = "" if point.plausible is None else str(point.plausible)
        note = point.tag or ""
        if point.derived_from_adsh:
            note += f" (from Q1/Q2/Q3 adshs={point.derived_from_adsh})"
        print(
            f"{point.period_end.isoformat():<12} {point.form:<6} "
            f"{str(point.fy):<6} {str(point.fp):<4} {value_str:>18}  "
            f"{point.source:<22} {plausible_str:<9} {note}"
        )


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL"]
    for ticker in tickers:
        _print_series_for_ticker(ticker)
