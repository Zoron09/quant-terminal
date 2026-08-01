"""Pulls a company's own sequential discrete-quarter net income and computes net
profit margin (NI / Revenue x 100) against the revenue pull.

Runnable directly for a manual eyeball check: python net_margin.py AAPL MSFT
"""
import sys
from typing import List, Optional

from code33.models import MarginPoint, QuarterlyNetMarginSeries, QuarterlyRevenueSeries
from code33.quarterly_engine import get_quarterly_series
from code33.revenue import get_quarterly_revenue_series
from code33.ticker_lookup import resolve_ticker_to_cik

# Priority-ordered net income tags: first tag with a valid value wins.
NI_TAGS = [
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",
]


def _is_implausible_net_income(derived_value: float, sibling_values: List[float]) -> bool:
    """Flags a derived Q4 NI as implausible only if its magnitude blows past 4x the
    average magnitude of that fiscal year's other three quarters. Unlike revenue,
    negative NI is a normal loss quarter (never flagged for that alone), and there's
    no floor check: NI can legitimately sit near zero right after a large-magnitude
    quarter, which isn't an error the way a near-zero revenue quarter would be."""
    if not sibling_values:
        return False
    avg_abs = sum(abs(v) for v in sibling_values) / len(sibling_values)
    if avg_abs <= 0:
        return False
    return abs(derived_value) > 4 * avg_abs


def get_quarterly_net_income_series(cik: int, quarters: int = 8) -> QuarterlyRevenueSeries:
    """Company's own sequential discrete-quarter net income figures, most recent first.
    Uses the same shared machinery as revenue (datapath-cached quarter reads, date-window
    Q4/FY derivation, restatement flagging) — just a different tag priority list and
    plausibility rule. See quarterly_engine.get_quarterly_series for full behavior.
    """
    return get_quarterly_series(cik, NI_TAGS, _is_implausible_net_income, quarters)


def pair_margin_series(
    revenue_series: QuarterlyRevenueSeries,
    ni_series: QuarterlyRevenueSeries,
    cik: int,
    quarters: int = 8,
) -> QuarterlyNetMarginSeries:
    """Pairs an already-built revenue series with an already-built net income
    series into per-quarter margins, carrying both legs' own source/plausible/
    restated flags through on each point. Joined strictly by period_end date,
    never by fiscal-year label."""
    if not revenue_series.is_usable and not revenue_series.points:
        return QuarterlyNetMarginSeries(cik=cik, points=[], series_flag=revenue_series.series_flag)
    if not ni_series.is_usable and not ni_series.points:
        return QuarterlyNetMarginSeries(cik=cik, points=[], series_flag=ni_series.series_flag)

    # Proximity join (±PAIR_TOLERANCE_DAYS), not exact-date equality: the two
    # legs can come from different sources for the same fiscal quarter (e.g.
    # revenue from secfsdstools, NI gap-filled from live EDGAR) with slightly
    # different period-end anchors. Each NI point pairs with at most one
    # revenue point (nearest wins).
    # Matches edgar_fill.MATCH_TOLERANCE_DAYS: absorbs secfsdstools' month-end
    # ddate rounding vs EDGAR's exact period ends when the two legs come from
    # different sources. Quarters sit ~91 days apart, so no ambiguity.
    PAIR_TOLERANCE_DAYS = 25
    ni_pool = list(ni_series.points)

    def take_nearest_ni(period_end):
        best = min(
            (p for p in ni_pool if abs((p.period_end - period_end).days) <= PAIR_TOLERANCE_DAYS),
            key=lambda p: abs((p.period_end - period_end).days),
            default=None,
        )
        if best is not None:
            ni_pool.remove(best)
        return best

    pairs = [(rp.period_end, rp, take_nearest_ni(rp.period_end)) for rp in revenue_series.points]
    pairs.extend((p.period_end, None, p) for p in ni_pool)  # NI-only leftovers
    pairs.sort(key=lambda x: x[0], reverse=True)

    points: List[MarginPoint] = []
    for period_end, rp, nip in pairs:

        revenue_value = rp.value if rp is not None else None
        ni_value = nip.value if nip is not None else None

        margin: Optional[float] = None
        if revenue_value is not None and ni_value is not None and revenue_value != 0:
            margin = round(ni_value / revenue_value * 100, 2)

        fy = rp.fy if rp is not None else (nip.fy if nip is not None else None)
        fp = rp.fp if rp is not None else (nip.fp if nip is not None else None)
        fiscal_quarter = f"{fy} {fp}" if fy is not None and fp is not None else "?"

        points.append(
            MarginPoint(
                period_end=period_end,
                fiscal_quarter=fiscal_quarter,
                net_income=ni_value,
                ni_source=nip.source if nip is not None else "missing",
                ni_plausible=nip.plausible if nip is not None else None,
                ni_restated=nip.restated if nip is not None else False,
                ni_restated_value=nip.restated_value if nip is not None else None,
                revenue=revenue_value,
                revenue_source=rp.source if rp is not None else "missing",
                revenue_plausible=rp.plausible if rp is not None else None,
                revenue_restated=rp.restated if rp is not None else False,
                revenue_restated_value=rp.restated_value if rp is not None else None,
                net_margin_pct=margin,
            )
        )

    return QuarterlyNetMarginSeries(cik=cik, points=points[:quarters])


def get_quarterly_net_margin(cik: int, quarters: int = 8) -> QuarterlyNetMarginSeries:
    """Net margin per quarter, pairing the existing revenue pull (reused, not
    reimplemented) with a net income pull on the same shared machinery. Both legs'
    own source/plausible/restated flags are carried through on each point."""
    revenue_series = get_quarterly_revenue_series(cik, quarters)
    ni_series = get_quarterly_net_income_series(cik, quarters)
    return pair_margin_series(revenue_series, ni_series, cik, quarters)


def _print_margin_for_ticker(ticker: str) -> None:
    cik = resolve_ticker_to_cik(ticker)
    if cik is None:
        print(f"{ticker}: could not resolve to a CIK")
        return

    series = get_quarterly_net_margin(cik)
    print(f"\n=== {ticker} (cik={cik}) ===")
    if not series.is_usable and not series.points:
        print(f"  UNUSABLE: {series.series_flag}")
        return

    header = (
        f"{'period_end':<12} {'fiscal_q':<10} {'net_income':>16} {'ni_source':<22} {'ni_ok':<6} "
        f"{'revenue':>16} {'rev_source':<22} {'rev_ok':<6} {'margin_%':>9}"
    )
    print(header)
    print("-" * len(header))
    for p in series.points:
        ni_str = f"{p.net_income:,.0f}" if p.net_income is not None else "N/A"
        rev_str = f"{p.revenue:,.0f}" if p.revenue is not None else "N/A"
        margin_str = f"{p.net_margin_pct:.2f}" if p.net_margin_pct is not None else "N/A"
        ni_ok = "" if p.ni_plausible is None else str(p.ni_plausible)
        rev_ok = "" if p.revenue_plausible is None else str(p.revenue_plausible)
        print(
            f"{p.period_end.isoformat():<12} {p.fiscal_quarter:<10} {ni_str:>16} {p.ni_source:<22} {ni_ok:<6} "
            f"{rev_str:>16} {p.revenue_source:<22} {rev_ok:<6} {margin_str:>9}"
        )


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL"]
    for ticker in tickers:
        _print_margin_for_ticker(ticker)
