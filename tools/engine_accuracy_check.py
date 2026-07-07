"""
Engine accuracy check vs StockAnalysis.com
====================================================
For each ticker: takes our engine's latest quarter (revenue, net margin) from
get_code33_data(), pulls the same quarter's revenue/net income from
StockAnalysis.com's quarterly financials table, and diffs them.

Period-alignment guard: StockAnalysis.com's default overview page shows TTM
figures, not quarterly — comparing against that would produce a meaningless
diff. This scrapes /financials/?p=quarterly instead and matches columns by
actual Period Ending date (within a tolerance window, since real fiscal
quarter-ends rarely land exactly on a calendar quarter-end — e.g. AAPL's is
Mar 28, not Mar 31). If no column matches, the ticker is reported as a period
mismatch rather than a false discrepancy.

Run: .venv/Scripts/python.exe tools/engine_accuracy_check.py
"""

import os
import re
import sys
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.code33_engine import get_code33_data
from scrapling.fetchers import Fetcher

TICKERS = ['AAPL', 'JPM', 'XOM', 'COST', 'DIS', 'PLTR', 'SHOP']
DATE_MATCH_TOLERANCE_DAYS = 15
REVENUE_DIFF_TOLERANCE_PCT = 3.0       # relative %
MARGIN_DIFF_TOLERANCE_PP = 1.5         # percentage points, matches EPS tol in test_code33_regression.py
REQUEST_DELAY_SEC = 1.5                # courtesy delay between StockAnalysis.com requests


def _parse_number(raw):
    """'111,184' -> 111184.0; '(1,234)' -> -1234.0; '-' or '' -> None."""
    raw = (raw or '').strip()
    if not raw or raw in ('-', '—', 'N/A'):
        return None
    negative = raw.startswith('(') and raw.endswith(')')
    cleaned = raw.strip('()').replace(',', '').replace('%', '').replace('$', '')
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if negative else val


def _parse_period_ending(raw):
    """"Mar '26\\nMar 28, 2026" -> date(2026, 3, 28)."""
    if not raw:
        return None
    last_line = raw.strip().splitlines()[-1].strip()
    try:
        return datetime.strptime(last_line, "%b %d, %Y").date()
    except ValueError:
        return None


def fetch_stockanalysis_quarterly(ticker):
    """Returns a list of {fiscal_label, period_ending, revenue, net_income} dicts,
    newest quarter first, or raises on unrecoverable fetch/parse failure."""
    url = f"https://stockanalysis.com/stocks/{ticker.lower()}/financials/?p=quarterly"
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} fetching {url}")

    tables = page.css('table')
    if not tables:
        raise RuntimeError("no <table> found on financials page")
    rows = tables[0].css('tr')

    def row_label(r):
        cells = r.css('th, td')
        return cells[0].get_all_text().strip() if cells else ''

    def row_values(r):
        return [c.text.strip() for c in r.css('th, td')]

    fiscal_row = period_row = revenue_row = ni_row = None
    for r in rows:
        label = row_label(r)
        if label == 'Fiscal Quarter':
            fiscal_row = row_values(r)
        elif label == 'Period Ending':
            period_row = [c.get_all_text().strip() for c in r.css('th, td')]
        elif label == 'Revenue' and revenue_row is None:
            revenue_row = row_values(r)
        elif label == 'Net Income' and ni_row is None:
            ni_row = row_values(r)

    if not (fiscal_row and period_row and revenue_row and ni_row):
        raise RuntimeError("could not find Fiscal Quarter / Period Ending / Revenue / Net Income rows")

    n = min(len(fiscal_row), len(period_row), len(revenue_row), len(ni_row))
    quarters = []
    for i in range(1, n):  # skip index 0 (row label column)
        period_ending = _parse_period_ending(period_row[i])
        if period_ending is None:
            continue
        quarters.append({
            'fiscal_label': fiscal_row[i],
            'period_ending': period_ending,
            'revenue': _parse_number(revenue_row[i]),
            'net_income': _parse_number(ni_row[i]),
        })
    return quarters


def check_ticker(ticker):
    result = {'ticker': ticker, 'error': None}
    try:
        data = get_code33_data(ticker)
        rev_list = data.get('rev') or []
        npm_list = data.get('npm') or []
        end_dates = data.get('rev_end_dates') or []
        if not rev_list or not end_dates:
            result['error'] = f"no engine revenue data (status={data.get('status')})"
            return result

        our_rev = rev_list[-1]
        our_npm = npm_list[-1] if npm_list else None
        our_period = datetime.strptime(end_dates[-1], "%Y-%m-%d").date()
        result.update({'our_period': our_period, 'our_rev': our_rev, 'our_npm': our_npm})

        sa_quarters = fetch_stockanalysis_quarterly(ticker)
        best = min(sa_quarters, key=lambda q: abs((q['period_ending'] - our_period).days), default=None)
        if best is None:
            result['error'] = "no quarters parsed from StockAnalysis.com"
            return result

        gap_days = abs((best['period_ending'] - our_period).days)
        if gap_days > DATE_MATCH_TOLERANCE_DAYS:
            result['period_mismatch'] = True
            result['sa_period'] = best['period_ending']
            result['gap_days'] = gap_days
            return result

        sa_rev = best['revenue']
        sa_ni = best['net_income']
        if sa_rev is None or sa_ni is None:
            result['error'] = f"StockAnalysis.com revenue/net income missing for matched period {best['period_ending']}"
            return result

        sa_margin = (sa_ni / sa_rev * 100) if sa_rev else None

        rev_diff_pct = (our_rev - sa_rev) / sa_rev * 100 if sa_rev else None
        margin_diff_pp = (our_npm - sa_margin) if (our_npm is not None and sa_margin is not None) else None

        flagged = (
            (rev_diff_pct is not None and abs(rev_diff_pct) > REVENUE_DIFF_TOLERANCE_PCT) or
            (margin_diff_pp is not None and abs(margin_diff_pp) > MARGIN_DIFF_TOLERANCE_PP)
        )

        result.update({
            'sa_period': best['period_ending'],
            'sa_rev': sa_rev,
            'sa_margin': sa_margin,
            'rev_diff_pct': rev_diff_pct,
            'margin_diff_pp': margin_diff_pp,
            'flagged': flagged,
        })
        return result
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {e}"
        return result


def _fmt_money(v):
    return f"${v:,.0f}" if v is not None else "—"


def _fmt_pct(v):
    return f"{v:.2f}%" if v is not None else "—"


def main():
    print(f"Tolerances: revenue diff > {REVENUE_DIFF_TOLERANCE_PCT}% (relative), "
          f"margin diff > {MARGIN_DIFF_TOLERANCE_PP}pp, date match window ±{DATE_MATCH_TOLERANCE_DAYS} days\n")

    rows = []
    for i, ticker in enumerate(TICKERS):
        rows.append(check_ticker(ticker))
        if i < len(TICKERS) - 1:
            time.sleep(REQUEST_DELAY_SEC)

    header = f"{'Ticker':<7}{'Period':<24}{'Our Rev':>14}{'SA Rev':>14}{'Rev Diff%':>10}{'Our Margin':>12}{'SA Margin':>11}{'Margin DiffPP':>14}  Flag"
    print(header)
    print("-" * len(header))

    for r in rows:
        ticker = r['ticker']
        if r.get('error'):
            print(f"{ticker:<7}{'ERROR: ' + r['error']:<90}")
            continue
        if r.get('period_mismatch'):
            our_p = r['our_period'].isoformat()
            sa_p = r['sa_period'].isoformat()
            print(f"{ticker:<7}PERIOD MISMATCH — our={our_p} vs SA closest={sa_p} ({r['gap_days']}d gap, >{DATE_MATCH_TOLERANCE_DAYS}d tolerance) — no diff computed")
            continue

        period_str = f"{r['our_period'].isoformat()} vs {r['sa_period'].isoformat()}"
        flag_str = "FLAGGED" if r['flagged'] else "ok"
        print(f"{ticker:<7}{period_str:<24}{_fmt_money(r['our_rev']):>14}{_fmt_money(r['sa_rev']):>14}"
              f"{_fmt_pct(r['rev_diff_pct']):>10}{_fmt_pct(r['our_npm']):>12}{_fmt_pct(r['sa_margin']):>11}"
              f"{_fmt_pct(r['margin_diff_pp']):>14}  {flag_str}")

    flagged_count = sum(1 for r in rows if r.get('flagged'))
    mismatch_count = sum(1 for r in rows if r.get('period_mismatch'))
    error_count = sum(1 for r in rows if r.get('error'))
    print(f"\n{len(rows)} tickers checked | {flagged_count} flagged | {mismatch_count} period mismatch | {error_count} errors")


if __name__ == "__main__":
    main()
