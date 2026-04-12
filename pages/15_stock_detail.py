"""
pages/15_stock_detail.py
Stock Detail Page — Ticker header, OHLC bar, price chart, 5 tabs.
Per CLAUDE.md Section 7. SEC EDGAR primary, yfinance fallback.
"""
import streamlit as st
import sys, os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info, get_financials, get_price_history
from utils.alpaca_client import get_bars, get_snapshots, _HAS_ALPACA
from utils.sec_edgar import get_cik
from utils.formatters import (
    fmt_number, fmt_large_number, fmt_pct, fmt_price,
    fmt_volume, fmt_fin, fmt_date, safe_get,
)

try:
    from utils.alpaca_client import ALPACA_KEY, ALPACA_SECRET
except Exception:
    ALPACA_KEY = ALPACA_SECRET = ''

try:
    from utils.finnhub_client import fh_earnings_surprises, fh_basic_financials, FINNHUB_KEY
    _HAS_FINNHUB = bool(FINNHUB_KEY)
except Exception:
    _HAS_FINNHUB = False
    FINNHUB_KEY = ''
    def fh_earnings_surprises(x): return None
    def fh_basic_financials(x): return None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Detail · Quant Terminal",
    page_icon="📋",
    layout="wide",
)

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

DARK   = '#0E1117'
BG     = '#161B22'
GREEN  = '#00FF41'
RED    = '#FF4444'
YELLOW = '#FFD700'
GRAY   = '#888888'
EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

# ── Utilities ─────────────────────────────────────────────────────────────────

def _nan(v):
    if v is None:
        return True
    try:
        return isinstance(v, float) and np.isnan(v)
    except Exception:
        return False


def _sf(v, default=None):
    if _nan(v):
        return default
    try:
        return float(v)
    except Exception:
        return default


def _time_ago(ts) -> str:
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.utcfromtimestamp(ts)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', ''))
        else:
            dt = ts
        diff = datetime.utcnow() - dt
        if diff.days >= 1:
            return f"{diff.days}d ago"
        h = diff.seconds // 3600
        if h >= 1:
            return f"{h}h ago"
        return f"{diff.seconds // 60}m ago"
    except Exception:
        return ''


def _fmt_cell(val, is_pct=False, already_pct=False):
    """Format a financial cell with colour for negatives."""
    if _nan(val):
        return '<span style="color:#555">—</span>'
    try:
        v = float(val)
        if is_pct:
            txt = f"{v:.1f}%" if already_pct else f"{v*100:.1f}%"
            c   = GREEN if v > 0 else (RED if v < 0 else '#FFFFFF')
            return f'<span style="color:{c}">{txt}</span>'
        neg = v < 0
        av  = abs(v)
        if av >= 1e12:
            s = f"{av/1e12:.2f}T"
        elif av >= 1e9:
            s = f"{av/1e9:.2f}B"
        elif av >= 1e6:
            s = f"{av/1e6:.1f}M"
        elif av >= 1e3:
            s = f"{av/1e3:.1f}K"
        else:
            s = f"{av:.2f}"
        if neg:
            return f'<span style="color:{RED}">({s})</span>'
        return s
    except Exception:
        return '<span style="color:#555">—</span>'


def _growth_cell(curr, prev):
    if _nan(curr) or _nan(prev) or prev == 0:
        return '<span style="color:#555">—</span>'
    try:
        g = (float(curr) - float(prev)) / abs(float(prev)) * 100
        c = GREEN if g >= 0 else RED
        sign = '+' if g >= 0 else ''
        return f'<span style="color:{c};font-size:11px;">{sign}{g:.1f}%</span>'
    except Exception:
        return '<span style="color:#555">—</span>'


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_edgar_facts(ticker: str) -> dict | None:
    if '.' in ticker:
        return None
    cik = get_cik(ticker)
    if not cik:
        return None
    try:
        url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
        r = requests.get(url, headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _edgar_series(facts: dict | None, concepts: list, unit: str = 'USD',
                  quarterly: bool = True, balance: bool = False) -> dict:
    """
    Extract a period time-series from EDGAR company facts.
    Returns {end_date_str: float_value} sorted ascending.
    """
    if not facts:
        return {}
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    if balance and quarterly:
        pat = re.compile(r'^CY\d{4}Q\dI$')
    elif balance:
        pat = re.compile(r'^CY\d{4}I$')
    elif quarterly:
        pat = re.compile(r'^CY\d{4}Q\d$')
    else:
        pat = re.compile(r'^CY\d{4}$')

    for concept in concepts:
        entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
        if not entries:
            continue
        filtered = [e for e in entries if pat.match(e.get('frame', ''))]
        if len(filtered) < 3:
            continue
        by_end: dict = {}
        for e in filtered:
            end = e.get('end', '')
            if not end:
                continue
            if end not in by_end or e.get('filed', '') > by_end[end].get('filed', ''):
                by_end[end] = e
        if len(by_end) >= 3:
            return {end: float(v['val']) for end, v in sorted(by_end.items())}
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def get_edgar_financials(ticker: str) -> dict:
    """
    Returns {income_q, income_a, balance_q, balance_a, cf_q, cf_a} DataFrames.
    EDGAR primary, yfinance fallback. DataFrames: rows=metrics, cols=dates desc.
    """
    facts = get_edgar_facts(ticker)
    yf    = get_financials(ticker)

    def _series_to_col(series: dict) -> pd.Series:
        return pd.Series({pd.Timestamp(k): v for k, v in series.items()})

    def _edgar_df(concept_rows, quarterly, balance=False):
        """Build DataFrame from EDGAR concept rows. Returns None on any failure."""
        try:
            data = {}
            for name, concepts, _ in concept_rows:
                s = _edgar_series(facts, concepts, quarterly=quarterly, balance=balance)
                if s:
                    data[name] = _series_to_col(s)
            if not data:
                return None
            df = pd.DataFrame(data).T
            df = df.sort_index(axis=1, ascending=False)
            return df
        except Exception:
            return None

    IS_CONCEPTS = [
        ('Revenue',          ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerIncludingAssessedTax'], ['Total Revenue', 'Revenue']),
        ('Gross Profit',     ['GrossProfit'],                                                                                                                               ['Gross Profit']),
        ('Operating Income', ['OperatingIncomeLoss'],                                                                                                                      ['Operating Income', 'EBIT']),
        ('Interest Expense', ['InterestExpense', 'InterestAndDebtExpense'],                                                                                                ['Interest Expense']),
        ('Net Income',       ['NetIncomeLoss'],                                                                                                                             ['Net Income', 'Net Income Common Stockholders']),
        ('EPS Diluted',      ['EarningsPerShareDiluted'],                                                                                                                  ['Diluted EPS', 'Basic EPS']),
        ('D&A',              ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization'],                                                                      []),
    ]
    BS_CONCEPTS = [
        ('Cash & Equivalents',        ['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsAndShortTermInvestments'], ['Cash And Cash Equivalents', 'Cash Financial']),
        ('Total Current Assets',      ['AssetsCurrent'],                                                                       ['Current Assets', 'Total Current Assets']),
        ('Total Assets',              ['Assets'],                                                                               ['Total Assets']),
        ('Total Current Liabilities', ['LiabilitiesCurrent'],                                                                  ['Current Liabilities', 'Total Current Liabilities']),
        ('Long-term Debt',            ['LongTermDebt', 'LongTermDebtNoncurrent'],                                              ['Long Term Debt', 'Long Term Debt And Capital Lease Obligation']),
        ('Total Liabilities',         ['Liabilities'],                                                                          ['Total Liabilities Net Minority Interest', 'Total Liabilities']),
        ('Total Equity',              ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'], ['Stockholders Equity', 'Common Stock Equity']),
    ]
    CF_CONCEPTS = [
        ('Operating Cash Flow', ['NetCashProvidedByUsedInOperatingActivities'],       ['Operating Cash Flow']),
        ('Capital Expenditure', ['PaymentsToAcquirePropertyPlantAndEquipment'],       ['Capital Expenditure']),
        ('Share Buybacks',      ['PaymentsForRepurchaseOfCommonStock'],               ['Repurchase Of Capital Stock']),
        ('Dividends Paid',      ['PaymentsOfDividends', 'PaymentsOfDividendsCommonStock'], ['Payment Of Dividends', 'Cash Dividends Paid']),
    ]

    def _yf_df(yf_key, concept_rows):
        try:
            df_yf = yf.get(yf_key)
            if df_yf is None or not isinstance(df_yf, pd.DataFrame) or df_yf.empty:
                return pd.DataFrame()
            result = {}
            for name, _, yf_keys in concept_rows:
                for k in yf_keys:
                    if k in df_yf.index:
                        result[name] = df_yf.loc[k]
                        break
            if len(result) == 0:
                return pd.DataFrame()
            return pd.DataFrame(result).T
        except Exception:
            return pd.DataFrame()

    out = {}
    for period, quarterly in [('q', True), ('a', False)]:
        # Income statement
        edgar_is = _edgar_df(IS_CONCEPTS, quarterly=quarterly)
        out[f'income_{period}'] = edgar_is if edgar_is is not None and len(edgar_is.columns) >= 3 \
            else _yf_df(f'income_{"quarterly" if quarterly else "annual"}', IS_CONCEPTS)

        # Balance sheet
        edgar_bs = _edgar_df(BS_CONCEPTS, quarterly=quarterly, balance=True)
        out[f'balance_{period}'] = edgar_bs if edgar_bs is not None and len(edgar_bs.columns) >= 3 \
            else _yf_df(f'balance_{"quarterly" if quarterly else "annual"}', BS_CONCEPTS)

        # Cash flow
        edgar_cf = _edgar_df(CF_CONCEPTS, quarterly=quarterly)
        out[f'cf_{period}'] = edgar_cf if edgar_cf is not None and len(edgar_cf.columns) >= 3 \
            else _yf_df(f'cashflow_{"quarterly" if quarterly else "annual"}', CF_CONCEPTS)

    return out


# ── News ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_stock_news(ticker: str) -> list:
    items = []
    seen: set = set()
    clean = ticker.upper().split('.')[0]

    if _HAS_FINNHUB:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        week  = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        try:
            r = requests.get(
                'https://finnhub.io/api/v1/company-news',
                params={'symbol': clean, 'from': week, 'to': today, 'token': FINNHUB_KEY},
                timeout=8,
            )
            for art in r.json():
                h = (art.get('headline') or '').strip()
                if h and h not in seen:
                    seen.add(h)
                    items.append({
                        'title':     h,
                        'source':    art.get('source', 'Finnhub'),
                        'published': _time_ago(art.get('datetime')),
                        'link':      art.get('url', ''),
                    })
        except Exception:
            pass

    try:
        if _HAS_ALPACA and ALPACA_KEY:
            r = requests.get(
                'https://data.alpaca.markets/v1beta1/news',
                params={'symbols': clean, 'limit': 30, 'sort': 'desc', 'include_content': 'false'},
                auth=(ALPACA_KEY, ALPACA_SECRET), timeout=8,
            )
            for art in r.json().get('news', []):
                h = (art.get('headline') or '').strip()
                if h and h not in seen:
                    seen.add(h)
                    items.append({
                        'title':     h,
                        'source':    art.get('source', 'Alpaca'),
                        'published': _time_ago(art.get('created_at') or art.get('updated_at', '')),
                        'link':      art.get('url', ''),
                    })
    except Exception:
        pass

    return items[:50]


# ── Financial table renderer ──────────────────────────────────────────────────

def _render_fin_table(df: pd.DataFrame, rows_spec: list, title: str,
                      chart_metric: str | None = None, chart_type: str = 'Bar'):
    """
    Render a financial statement section.
    rows_spec: [(display_name, type)] where type = 'raw' | 'pct' | 'computed_growth' | 'margin'
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning(f"{title}: Data unavailable.")
        return

    cols_all = [c for c in df.columns][:8]
    date_strs = [str(c)[:10] for c in cols_all]

    # Mini chart of the key metric
    if chart_metric and chart_metric in df.index and len(cols_all) > 1:
        vals = [_sf(df.loc[chart_metric, c]) for c in cols_all]
        vals_rev = list(reversed(vals))
        dates_rev = list(reversed(date_strs))
        valid_mask = [v is not None for v in vals_rev]
        if any(valid_mask):
            fig = go.Figure()
            if chart_type == 'Bar':
                colors = [GREEN if (v or 0) >= 0 else RED for v in vals_rev]
                fig.add_trace(go.Bar(
                    x=dates_rev, y=vals_rev, marker_color=colors,
                    text=[_fmt_cell(v) if v else '' for v in vals_rev],
                    textposition='outside', textfont_color='white',
                ))
            else:
                fig.add_trace(go.Scatter(
                    x=dates_rev, y=vals_rev,
                    line=dict(color=GREEN, width=2),
                    fill='tozeroy', fillcolor='rgba(0,255,65,0.06)',
                ))
            fig.update_layout(
                paper_bgcolor=DARK, plot_bgcolor=BG,
                height=160, margin=dict(t=5, b=5, l=5, r=5),
                yaxis=dict(gridcolor='#222', color=GRAY, showticklabels=True, tickfont_size=9),
                xaxis=dict(color=GRAY, tickfont_size=9),
                font=dict(color='white', family='Courier New'),
                showlegend=False,
                title=dict(text=f'{chart_metric}', font=dict(color=GRAY, size=11)),
            )
            st.plotly_chart(fig, use_container_width=True)

    # Build HTML table
    header_cols = ''.join(f'<th style="text-align:right;color:{GRAY};font-size:11px;padding:4px 8px;">{d}</th>'
                          for d in date_strs)
    html = f'''
<div style="overflow-x:auto;margin-bottom:20px;">
<table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">
<thead><tr>
  <th style="text-align:left;color:{GRAY};font-size:11px;padding:4px 8px;min-width:200px;">{title}</th>
  {header_cols}
</tr></thead>
<tbody>
'''
    for row_name, row_type in rows_spec:
        if row_type == 'section_header':
            html += f'<tr><td colspan="{len(cols_all)+1}" style="padding:8px 6px 2px 6px;color:{GRAY};font-size:10px;letter-spacing:1px;border-top:1px solid #222;">{row_name}</td></tr>\n'
            continue

        if row_name not in df.index:
            # Try to compute
            if row_type == 'computed_growth' and row_name.replace(' Growth YoY%', '') in df.index:
                base_row = row_name.replace(' Growth YoY%', '')
                base_data = [_sf(df.loc[base_row, c]) for c in cols_all]
                cells = []
                for i, col in enumerate(cols_all):
                    if i == len(cols_all) - 1:
                        cells.append('<span style="color:#555">—</span>')
                    else:
                        cells.append(_growth_cell(base_data[i], base_data[i + 1]))
                vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
                row_label = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{row_name}</span>'
                html += f'<tr style="border-top:1px solid #1a1a1a;">'
                html += f'<td style="padding:4px 8px;">{row_label}</td>{vals_html}</tr>\n'
                continue
            elif row_type == 'margin' and row_name in ('Gross Margin%', 'Operating Margin%', 'Net Margin%', 'EPS Growth YoY%'):
                num_key = row_name.replace(' Margin%', '').replace(' Growth YoY%', '')
                num_map = {
                    'Gross': 'Gross Profit', 'Operating': 'Operating Income', 'Net': 'Net Income', 'EPS': 'EPS Diluted'
                }
                num_row = num_map.get(num_key.split()[0], '')
                if num_row not in df.index or 'Revenue' not in df.index:
                    continue
                cells = []
                for col in cols_all:
                    n = _sf(df.loc[num_row, col])
                    d = _sf(df.loc['Revenue', col]) if 'Revenue' in df.index else None
                    if n is not None and d and d != 0:
                        margin = n / d * 100
                        c = GREEN if margin > 0 else RED
                        cells.append(f'<span style="color:{c}">{margin:.1f}%</span>')
                    else:
                        cells.append('<span style="color:#555">—</span>')
                vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
                row_label = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{row_name}</span>'
                html += f'<tr style="border-top:1px solid #1a1a1a;">'
                html += f'<td style="padding:4px 8px;">{row_label}</td>{vals_html}</tr>\n'
                continue
            elif row_type == 'free_cf':
                # FCF = OCF - CapEx
                ocf_vals = [_sf(df.loc['Operating Cash Flow', c]) if 'Operating Cash Flow' in df.index else None for c in cols_all]
                cx_vals  = [_sf(df.loc['Capital Expenditure', c]) if 'Capital Expenditure' in df.index else None for c in cols_all]
                cells = []
                for o, x in zip(ocf_vals, cx_vals):
                    if o is not None and x is not None:
                        fcf = o - abs(x)
                        cells.append(_fmt_cell(fcf))
                    else:
                        cells.append('<span style="color:#555">—</span>')
                vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
                html += f'<tr style="border-top:1px solid #1a1a1a;">'
                html += f'<td style="padding:4px 8px;">Free Cash Flow</td>{vals_html}</tr>\n'
                continue
            elif row_type == 'ebitda':
                # EBITDA = Operating Income + D&A
                oi_vals  = [_sf(df.loc['Operating Income', c]) if 'Operating Income' in df.index else None for c in cols_all]
                da_vals  = [_sf(df.loc['D&A', c]) if 'D&A' in df.index else None for c in cols_all]
                cells = []
                for oi, da in zip(oi_vals, da_vals):
                    if oi is not None and da is not None:
                        cells.append(_fmt_cell(oi + abs(da)))
                    elif oi is not None:
                        cells.append('<span style="color:#555">—</span>')
                    else:
                        cells.append('<span style="color:#555">—</span>')
                vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
                html += f'<tr style="border-top:1px solid #1a1a1a;">'
                html += f'<td style="padding:4px 8px;">EBITDA</td>{vals_html}</tr>\n'
                continue
            else:
                continue

        raw = [_sf(df.loc[row_name, c]) for c in cols_all]
        is_pct_row = row_type in ('pct',)

        if row_type == 'growth_row':
            cells = []
            for i, v in enumerate(raw):
                if i == len(raw) - 1:
                    cells.append('<span style="color:#555">—</span>')
                else:
                    cells.append(_growth_cell(raw[i], raw[i + 1]))
            vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
            row_label = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{row_name}</span>'
        else:
            cells = [_fmt_cell(v, is_pct=is_pct_row, already_pct=True) for v in raw]
            vals_html = ''.join(f'<td style="text-align:right;padding:4px 8px;">{c}</td>' for c in cells)
            bold = 'font-weight:bold;' if row_type == 'bold' else ''
            row_label = f'<span style="{bold}">{row_name}</span>'

        html += f'<tr style="border-top:1px solid #1a1a1a;">'
        html += f'<td style="padding:4px 8px;">{row_label}</td>{vals_html}</tr>\n'

    html += '</tbody></table></div>'
    st.markdown(html, unsafe_allow_html=True)


# ── Code 33 helpers ───────────────────────────────────────────────────────────

def _compute_yoy_growth(vals: list) -> list:
    """
    Given a list of quarterly values (oldest→newest), compute YoY growth rates.
    YoY[i] = (vals[i] - vals[i-4]) / |vals[i-4]| * 100 for i >= 4.
    Returns list of (date_label, growth_rate) for last available quarters.
    """
    rates = []
    for i in range(4, len(vals)):
        curr, prev = vals[i], vals[i - 4]
        if curr is not None and prev is not None and prev != 0 and not _nan(curr) and not _nan(prev):
            rates.append((float(curr) - float(prev)) / abs(float(prev)) * 100)
        else:
            rates.append(None)
    return rates


def _code33_metric_status(rates_3: list) -> tuple:
    """
    Given [G1, G2, G3] (3 growth rates oldest→newest), return:
    (status, d1, d2)
    where status = 'green'|'yellow'|'red'|'insufficient'
    d1 = G2 - G1, d2 = G3 - G2
    """
    valid = [r for r in rates_3 if r is not None]
    if len(valid) < 3:
        return 'insufficient', None, None
    g1, g2, g3 = valid[-3], valid[-2], valid[-1]
    d1 = g2 - g1
    d2 = g3 - g2
    if d1 < 0 or d2 < 0:
        return 'red', d1, d2
    # Both deltas positive
    if d2 >= d1:
        return 'green', d1, d2     # acceleration itself accelerating
    return 'yellow', d1, d2        # decelerating but still positive deltas


def _delta_color(d):
    if d is None:
        return GRAY
    if d > 0:
        return GREEN
    if d < 0:
        return RED
    return YELLOW


def _rate_badge(rate):
    if rate is None:
        return f'<span style="color:{GRAY}">N/A</span>'
    c = GREEN if rate > 0 else RED
    return f'<span style="color:{c};font-weight:bold;">{rate:+.1f}%</span>'


def _delta_badge(d, label=''):
    if d is None:
        return f'<span style="color:{GRAY}">—</span>'
    c = _delta_color(d)
    sign = '+' if d >= 0 else ''
    arrow = '▲' if d > 0 else ('▼' if d < 0 else '■')
    return f'<span style="color:{c}">{arrow} {sign}{d:.1f} pp</span>'


# ── Main render ───────────────────────────────────────────────────────────────

ticker = render_sidebar()
st.markdown("## 📋 Stock Detail")

if not ticker:
    st.info("Enter a ticker symbol in the sidebar to begin.")
    st.stop()

is_us = '.' not in ticker and not ticker.startswith('^')

# ── Load all data in parallel (cached) ───────────────────────────────────────
with st.spinner(f"Loading {ticker} …"):
    try:
        info = get_ticker_info(ticker)
    except Exception:
        info = {}
    try:
        bars_3y = get_price_history(ticker, period='3y', interval='1d')
    except Exception:
        bars_3y = pd.DataFrame()
    try:
        snaps = get_snapshots((ticker.upper(),)) if is_us and _HAS_ALPACA else {}
    except Exception:
        snaps = {}
    try:
        fin = get_edgar_financials(ticker)
    except Exception:
        fin = {}
    try:
        yf_fin = get_financials(ticker)
    except Exception:
        yf_fin = {}

snap   = snaps.get(ticker.upper(), {})

# ── Current price ─────────────────────────────────────────────────────────────
price      = _sf(snap.get('price')) or _sf(safe_get(info, 'currentPrice')) or _sf(safe_get(info, 'regularMarketPrice'))
prev_close = _sf(snap.get('prev_close')) or _sf(safe_get(info, 'regularMarketPreviousClose'))
chg        = (price - prev_close) if (price is not None and prev_close is not None) else None
chg_pct    = (chg / prev_close * 100) if (chg is not None and prev_close is not None and prev_close != 0) else None

open_p  = _sf(snap.get('open'))  or _sf(safe_get(info, 'open'))
high_p  = _sf(snap.get('high'))  or _sf(safe_get(info, 'dayHigh'))
low_p   = _sf(snap.get('low'))   or _sf(safe_get(info, 'dayLow'))
vol_p   = snap.get('volume')     or safe_get(info, 'volume')

# 52W high/low + avg volume from bars
hi52 = lo52 = avg_vol = None
if bars_3y is not None and not bars_3y.empty:
    last_252 = bars_3y.tail(252)
    hi52     = _sf(last_252['High'].max())
    lo52     = _sf(last_252['Low'].min())
    avg_vol  = _sf(bars_3y['Volume'].tail(50).mean())

hi52  = hi52  or _sf(safe_get(info, 'fiftyTwoWeekHigh'))
lo52  = lo52  or _sf(safe_get(info, 'fiftyTwoWeekLow'))
avg_vol_info = _sf(safe_get(info, 'averageVolume'))
avg_vol = avg_vol or avg_vol_info

name     = safe_get(info, 'longName') or safe_get(info, 'shortName') or ticker
exchange = safe_get(info, 'exchange') or safe_get(info, 'market') or ''
sector   = safe_get(info, 'sector') or ''

# ── Header ─────────────────────────────────────────────────────────────────────
chg_color = GREEN if (chg and chg >= 0) else RED
price_str  = f"${price:,.2f}" if price else "—"
chg_str    = f"{'+'if chg and chg>=0 else ''}{chg:.2f} ({chg_pct:+.2f}%)" if (chg and chg_pct) else "—"

st.markdown(f"""
<div style="background:{BG};border:1px solid #333;border-radius:8px;
            padding:20px 24px;margin-bottom:12px;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px;">
    <div>
      <div style="color:{GRAY};font-size:12px;font-family:monospace;letter-spacing:1px;">
        {ticker.upper()} &nbsp;·&nbsp; {exchange} &nbsp;·&nbsp; {sector}
      </div>
      <div style="color:#FFFFFF;font-size:20px;font-weight:bold;margin:4px 0;">
        {name}
      </div>
      <div style="display:flex;align-items:baseline;gap:16px;margin-top:6px;">
        <span style="color:#FFFFFF;font-size:36px;font-weight:bold;font-family:\'Courier New\',monospace;">
          {price_str}
        </span>
        <span style="color:{chg_color};font-size:18px;font-weight:bold;font-family:monospace;">
          {chg_str}
        </span>
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── OHLC Bar ──────────────────────────────────────────────────────────────────
def _ohlc_cell(label, value, fmt_fn=None):
    v = fmt_fn(value) if fmt_fn and value else (f"${value:,.2f}" if value else "—")
    return f'''
<div style="text-align:center;padding:8px 12px;">
  <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>
  <div style="color:#FFFFFF;font-size:14px;font-weight:bold;font-family:monospace;margin-top:3px;">{v}</div>
</div>'''

ohlc_html = f'''
<div style="background:{BG};border:1px solid #333;border-radius:6px;
            display:flex;flex-wrap:wrap;margin-bottom:16px;">
  {_ohlc_cell("OPEN", open_p)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("HIGH", high_p)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("LOW", low_p)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("PREV CLOSE", prev_close)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("VOLUME", vol_p, fmt_volume)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("AVG VOL (50D)", avg_vol, fmt_volume)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("52W HIGH", hi52)}
  <div style="width:1px;background:#333;margin:8px 0;"></div>
  {_ohlc_cell("52W LOW", lo52)}
</div>
'''
st.markdown(ohlc_html, unsafe_allow_html=True)

# ── Price Chart ───────────────────────────────────────────────────────────────
range_opts = {'1D': 1, '1W': 7, '1M': 30, '3M': 90, '6M': 180, '1Y': 365}
sel_range  = st.radio('Range', list(range_opts.keys()), horizontal=True, index=3, label_visibility='collapsed')
days = range_opts[sel_range]

chart_df = pd.DataFrame()
if bars_3y is not None and not bars_3y.empty:
    cutoff   = bars_3y.index[-1] - timedelta(days=days)
    chart_df = bars_3y[bars_3y.index >= cutoff].copy()

if not chart_df.empty:
    first_price = _sf(chart_df['Close'].iloc[0])
    last_price  = _sf(chart_df['Close'].iloc[-1])
    line_color  = GREEN if (first_price and last_price and last_price >= first_price) else RED

    fig_chart = go.Figure()
    fig_chart.add_trace(go.Scatter(
        x=chart_df.index, y=chart_df['Close'],
        line=dict(color=line_color, width=2),
        fill='tozeroy', fillcolor=f'rgba({",".join(str(int(line_color.lstrip("#")[i:i+2],16)) for i in (0,2,4))},0.08)',
        name='Close',
        hovertemplate='%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>',
    ))
    fig_chart.update_layout(
        paper_bgcolor=DARK, plot_bgcolor=BG,
        height=320, margin=dict(t=10, b=10, l=10, r=10),
        yaxis=dict(gridcolor='#222', color=GRAY, tickprefix='$'),
        xaxis=dict(color=GRAY, rangeslider=dict(visible=False)),
        font=dict(color='white', family='Courier New'),
        showlegend=False,
        hovermode='x unified',
    )
    st.plotly_chart(fig_chart, use_container_width=True)
else:
    st.warning("No price history available.")

st.markdown("---")

# ── 5 Tabs ────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Overview", "Financials", "Earnings", "Code 33", "News"
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    fh_metrics = fh_basic_financials(ticker.upper()) if _HAS_FINNHUB and is_us else None
    fhm = fh_metrics.get('metric', {}) if isinstance(fh_metrics, dict) else {}

    mkt_cap   = _sf(safe_get(info, 'marketCap'))
    pe_ttm    = _sf(safe_get(info, 'trailingPE')) or _sf(fhm.get('peTTM'))
    pe_fwd    = _sf(safe_get(info, 'forwardPE'))  or _sf(fhm.get('peForwardTTM')) or _sf(fhm.get('peExclExtraTTM'))
    eps_ttm   = _sf(safe_get(info, 'trailingEps')) or _sf(fhm.get('epsTTM'))
    rev_ttm   = _sf(safe_get(info, 'totalRevenue')) or _sf(fhm.get('revenueTTM'))
    gross_mgn = _sf(safe_get(info, 'grossMargins')) or _sf(fhm.get('grossMarginTTM'))
    net_mgn   = _sf(safe_get(info, 'profitMargins')) or _sf(fhm.get('netProfitMarginTTM'))
    beta      = _sf(safe_get(info, 'beta'))        or _sf(fhm.get('beta'))
    roe       = _sf(safe_get(info, 'returnOnEquity')) or _sf(fhm.get('roeTTM'))
    de_ratio  = _sf(safe_get(info, 'debtToEquity'))  or _sf(fhm.get('totalDebt/totalEquityAnnual'))
    div_yield = _sf(safe_get(info, 'dividendYield'))  or _sf(fhm.get('dividendYieldIndicatedAnnual'))
    float_sh  = _sf(safe_get(info, 'floatShares'))

    def _metric_card(label, value, fmt='number', suffix='', prefix=''):
        if value is None or _nan(value):
            disp = "N/A"
            col  = GRAY
        elif fmt == 'large':
            disp = fmt_large_number(value)
            col  = '#FFFFFF'
        elif fmt == 'pct':
            disp = f"{value*100:.1f}%"
            col  = GREEN if value > 0 else (RED if value < 0 else '#FFFFFF')
        elif fmt == 'pct_raw':
            disp = f"{value:.1f}%"
            col  = GREEN if value > 0 else (RED if value < 0 else '#FFFFFF')
        elif fmt == 'price':
            disp = f"${value:,.2f}"
            col  = '#FFFFFF'
        elif fmt == 'shares':
            disp = fmt_large_number(value, symbol='')
            col  = '#FFFFFF'
        else:
            disp = f"{prefix}{value:,.2f}{suffix}"
            col  = '#FFFFFF'
        return f'''
<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">
  <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>
  <div style="color:{col};font-size:20px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{disp}</div>
</div>'''

    # Row 1
    r1a, r1b, r1c, r1d = st.columns(4)
    r1a.markdown(_metric_card("MARKET CAP",     mkt_cap,   fmt='large'), unsafe_allow_html=True)
    r1b.markdown(_metric_card("P/E TTM",         pe_ttm,    fmt='number', prefix='', suffix='x'), unsafe_allow_html=True)
    r1c.markdown(_metric_card("P/E FORWARD",     pe_fwd,    fmt='number', prefix='', suffix='x'), unsafe_allow_html=True)
    r1d.markdown(_metric_card("EPS TTM",         eps_ttm,   fmt='price'), unsafe_allow_html=True)

    st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

    # Row 2
    r2a, r2b, r2c, r2d = st.columns(4)
    r2a.markdown(_metric_card("REVENUE TTM",     rev_ttm,   fmt='large'), unsafe_allow_html=True)
    r2b.markdown(_metric_card("GROSS MARGIN",    gross_mgn, fmt='pct'), unsafe_allow_html=True)
    r2c.markdown(_metric_card("NET MARGIN",      net_mgn,   fmt='pct'), unsafe_allow_html=True)
    r2d.markdown(_metric_card("BETA",            beta,      fmt='number', suffix=''), unsafe_allow_html=True)

    st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

    # Row 3
    r3a, r3b, r3c, r3d = st.columns(4)
    r3a.markdown(_metric_card("ROE",             roe,       fmt='pct'), unsafe_allow_html=True)
    de_disp = de_ratio / 100 if de_ratio and de_ratio > 10 else de_ratio  # yf returns as % sometimes
    r3b.markdown(_metric_card("DEBT / EQUITY",   de_disp,   fmt='number', suffix='x'), unsafe_allow_html=True)
    r3c.markdown(_metric_card("DIVIDEND YIELD",  div_yield, fmt='pct'), unsafe_allow_html=True)
    r3d.markdown(_metric_card("FLOAT SHARES",    float_sh,  fmt='shares'), unsafe_allow_html=True)

    # Company description
    desc = safe_get(info, 'longBusinessSummary') or ''
    if desc:
        st.markdown("<div style='margin:16px 0 4px 0;'></div>", unsafe_allow_html=True)
        with st.expander("Company Description", expanded=False):
            st.markdown(f"<div style='color:#CCCCCC;font-size:13px;line-height:1.6;'>{desc}</div>",
                        unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — FINANCIALS
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    col_period, col_chart_type = st.columns([1, 1])
    with col_period:
        period_sel = st.radio("Period", ["Quarterly", "Annual"], horizontal=True)
    with col_chart_type:
        chart_type_sel = st.radio("Chart", ["Bar", "Line"], horizontal=True)

    period_key = 'q' if period_sel == 'Quarterly' else 'a'
    yf_period  = 'quarterly' if period_sel == 'Quarterly' else 'annual'

    income_df  = fin.get(f'income_{period_key}',  pd.DataFrame())
    balance_df = fin.get(f'balance_{period_key}', pd.DataFrame())
    cf_df      = fin.get(f'cf_{period_key}',      pd.DataFrame())

    # ── Income Statement ──
    st.markdown(f"### Income Statement &nbsp;<span style='color:{GRAY};font-size:13px;'>({period_sel})</span>",
                unsafe_allow_html=True)

    IS_ROWS = [
        ('Revenue',              'bold'),
        ('Revenue Growth YoY%',  'computed_growth'),
        ('Gross Profit',         'raw'),
        ('Gross Margin%',        'margin'),
        ('Operating Income',     'raw'),
        ('Operating Margin%',    'margin'),
        ('EBITDA',               'ebitda'),
        ('Interest Expense',     'raw'),
        ('Net Income',           'bold'),
        ('Net Margin%',          'margin'),
        ('EPS Diluted',          'raw'),
        ('EPS Growth YoY%',      'computed_growth'),
    ]
    _render_fin_table(income_df, IS_ROWS, "Income Statement", 'Revenue', chart_type_sel)

    # ── Balance Sheet ──
    st.markdown(f"### Balance Sheet &nbsp;<span style='color:{GRAY};font-size:13px;'>({period_sel})</span>",
                unsafe_allow_html=True)
    BS_ROWS = [
        ('Cash & Equivalents',        'raw'),
        ('Total Current Assets',      'raw'),
        ('Total Assets',              'bold'),
        ('Total Current Liabilities', 'raw'),
        ('Long-term Debt',            'raw'),
        ('Total Liabilities',         'bold'),
        ('Total Equity',              'bold'),
    ]
    _render_fin_table(balance_df, BS_ROWS, "Balance Sheet", 'Total Assets', chart_type_sel)

    # ── Cash Flow ──
    st.markdown(f"### Cash Flow &nbsp;<span style='color:{GRAY};font-size:13px;'>({period_sel})</span>",
                unsafe_allow_html=True)
    CF_ROWS = [
        ('Operating Cash Flow', 'bold'),
        ('Capital Expenditure', 'raw'),
        ('Free Cash Flow',      'free_cf'),
        ('Share Buybacks',      'raw'),
        ('Dividends Paid',      'raw'),
    ]
    _render_fin_table(cf_df, CF_ROWS, "Cash Flow", 'Operating Cash Flow', chart_type_sel)

    st.caption("Primary source: SEC EDGAR · Fallback: yfinance")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — EARNINGS
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    surprises = fh_earnings_surprises(ticker.upper()) if _HAS_FINNHUB and is_us else None
    yf_ed     = get_financials(ticker)

    # Next earnings date
    next_date = None
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        if isinstance(cal, dict):
            ed = cal.get('Earnings Date')
            if isinstance(ed, list) and ed:
                next_date = str(ed[0])[:10]
            elif ed is not None:
                next_date = str(ed)[:10]
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            try:
                next_date = str(cal.loc['Earnings Date'].iloc[0])[:10]
            except Exception:
                pass
    except Exception:
        pass

    # Last reported date, beat rates
    last_date = eps_beat_rate = rev_beat_rate = None
    if surprises and isinstance(surprises, list) and len(surprises) > 0:
        last_date = surprises[0].get('period', '')
        last8 = surprises[:8]
        eps_beats = sum(1 for s in last8 if (_sf(s.get('surprisePercent')) or 0) > 0)
        eps_beat_rate = eps_beats / len(last8) * 100 if len(last8) > 0 else None

    # Insight cards
    def _insight_card(label, value, color='#FFFFFF'):
        v = value or '—'
        return f'''
<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">
  <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>
  <div style="color:{color};font-size:18px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{v}</div>
</div>'''

    beat_color = GREEN if eps_beat_rate and eps_beat_rate >= 70 else (YELLOW if eps_beat_rate and eps_beat_rate >= 50 else RED)
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.markdown(_insight_card("LAST REPORTED",         last_date or '—'),        unsafe_allow_html=True)
    ic2.markdown(_insight_card("NEXT EARNINGS EST",     next_date or '—'),        unsafe_allow_html=True)
    ic3.markdown(_insight_card("EPS BEAT RATE (8Q)",    f"{eps_beat_rate:.0f}%" if eps_beat_rate is not None else '—', color=beat_color), unsafe_allow_html=True)
    ic4.markdown(_insight_card("REV BEAT RATE (8Q)",    '—'),                     unsafe_allow_html=True)

    st.markdown("<div style='margin:16px 0 8px 0;'></div>", unsafe_allow_html=True)

    if surprises and isinstance(surprises, list) and len(surprises) > 0:
        # Build surprise table
        rows_html = ''
        for s in surprises[:12]:
            period    = s.get('period', '')
            eps_est   = _sf(s.get('estimate'))
            eps_act   = _sf(s.get('actual'))
            eps_surp  = _sf(s.get('surprisePercent'))
            # Finnhub doesn't return revenue surprise in basic endpoint — show N/A
            def _surp_cell(pct):
                if pct is None:
                    return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
                c = GREEN if pct > 0 else RED
                return f'<td style="text-align:right;padding:6px 10px;color:{c};font-weight:bold;">{pct:+.1f}%</td>'

            def _val_cell(v):
                if v is None:
                    return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
                return f'<td style="text-align:right;padding:6px 10px;">{v:.2f}</td>'

            rows_html += f'''
<tr style="border-bottom:1px solid #1a1a1a;">
  <td style="padding:6px 10px;color:{GRAY};font-family:monospace;">{period}</td>
  {_val_cell(eps_est)}
  {_val_cell(eps_act)}
  {_surp_cell(eps_surp)}
  <td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>
  <td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>
  <td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>
</tr>'''

        hdr = f'<th style="color:{GRAY};font-size:11px;padding:6px 10px;text-align:right;">'
        table_html = f'''
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">
<thead style="background:{BG};">
<tr>
  <th style="color:{GRAY};font-size:11px;padding:6px 10px;text-align:left;">Quarter</th>
  {hdr}EPS Est</th>
  {hdr}EPS Actual</th>
  {hdr}EPS Surprise%</th>
  {hdr}Rev Est</th>
  {hdr}Rev Actual</th>
  {hdr}Rev Surprise%</th>
</tr>
</thead>
<tbody>{rows_html}</tbody>
</table></div>'''
        st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.info("Earnings surprise data not available (Finnhub).")

    st.caption("Source: Finnhub")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — CODE 33
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown(f"### Code 33 — Minervini Fundamental Acceleration")

    # ── Extract quarterly data ────────────────────────────────────────────────
    q_income   = yf_fin.get('income_quarterly')
    edgar_q_is = fin.get('income_q')

    def _get_quarterly_vals(df, keys):
        """Extract a quarterly series from a DataFrame, oldest→newest."""
        if df is None or (hasattr(df, 'empty') and df.empty):
            return []
        try:
            for k in keys:
                if k in df.index:
                    cols_sorted = sorted(df.columns)
                    vals = [_sf(df.loc[k, c]) for c in cols_sorted]
                    return vals
        except Exception:
            pass
        return []

    # EPS Diluted quarterly
    eps_q_keys = ['Diluted EPS', 'Basic EPS', 'EPS Diluted']
    rev_q_keys = ['Total Revenue', 'Revenue']
    ni_q_keys  = ['Net Income', 'Net Income Common Stockholders']

    # Try edgar_q_is first (it uses our renamed rows), then yf_fin
    def _get_from_edgar_or_yf(edgar_df, yf_df, edgar_key, yf_keys):
        try:
            if edgar_df is not None and not (hasattr(edgar_df, 'empty') and edgar_df.empty):
                if edgar_key in edgar_df.index:
                    cols_sorted = sorted(edgar_df.columns)
                    return [_sf(edgar_df.loc[edgar_key, c]) for c in cols_sorted]
        except Exception:
            pass
        return _get_quarterly_vals(yf_df, yf_keys)

    eps_vals = _get_from_edgar_or_yf(edgar_q_is, q_income, 'EPS Diluted',  ['Diluted EPS', 'Basic EPS'])
    rev_vals = _get_from_edgar_or_yf(edgar_q_is, q_income, 'Revenue',       ['Total Revenue', 'Revenue'])
    ni_vals  = _get_from_edgar_or_yf(edgar_q_is, q_income, 'Net Income',    ['Net Income', 'Net Income Common Stockholders'])

    # Compute YoY growth rates (need 4+ quarters for YoY)
    eps_yoy = _compute_yoy_growth(eps_vals)
    rev_yoy = _compute_yoy_growth(rev_vals)

    # Compute quarterly net profit margin series
    def _margin_series(ni, rev):
        """Compute margin for each quarter: NI/Revenue * 100."""
        margins = []
        for n, r in zip(ni, rev):
            if n is not None and r is not None and r != 0 and not _nan(n) and not _nan(r):
                margins.append(float(n) / float(r) * 100)
            else:
                margins.append(None)
        return margins

    # Align rev and ni to same length
    min_len_rev_ni = min(len(rev_vals), len(ni_vals))
    margin_vals = _margin_series(ni_vals[:min_len_rev_ni], rev_vals[:min_len_rev_ni])

    # Get last 3 valid quarters for each metric
    def _last3_valid(lst):
        valid = [(i, v) for i, v in enumerate(lst) if v is not None]
        return valid[-3:] if len(valid) >= 3 else []

    eps_last3  = [v for _, v in _last3_valid(eps_yoy)]
    rev_last3  = [v for _, v in _last3_valid(rev_yoy)]
    mgn_last3  = [v for _, v in _last3_valid(margin_vals[-len(eps_yoy):] if len(margin_vals) > len(eps_yoy) else margin_vals)]

    # Compute Code 33 status per metric
    eps_status, eps_d1, eps_d2 = _code33_metric_status(eps_last3)
    rev_status, rev_d1, rev_d2 = _code33_metric_status(rev_last3)
    mgn_status, mgn_d1, mgn_d2 = _code33_metric_status(mgn_last3)

    # Overall Code 33 status
    status_order = {'red': 0, 'yellow': 1, 'green': 2, 'insufficient': -1}
    statuses = [eps_status, rev_status, mgn_status]

    if 'insufficient' in statuses:
        overall_status = 'insufficient'
    elif 'red' in statuses:
        overall_status = 'red'
    elif 'yellow' in statuses:
        overall_status = 'yellow'
    else:
        overall_status = 'green'

    badge_map = {
        'green':       (GREEN,  'ACTIVE',       'All 3 metrics accelerating for 3 consecutive quarters'),
        'yellow':      (YELLOW, 'AT RISK',      'Acceleration slowing — watch for reversal'),
        'red':         (RED,    'BROKEN',        'Deceleration detected — Code 33 is NOT active'),
        'insufficient':(GRAY,   'INSUFFICIENT', 'Not enough quarterly data to evaluate Code 33'),
    }
    badge_color, badge_label, badge_note = badge_map[overall_status]

    # Status badge
    st.markdown(f"""
<div style="background:{BG};border:2px solid {badge_color};border-radius:8px;
            padding:16px 24px;margin-bottom:20px;display:flex;align-items:center;gap:20px;">
  <div>
    <div style="color:{GRAY};font-size:11px;font-family:monospace;letter-spacing:2px;">CODE 33 STATUS</div>
    <div style="color:{badge_color};font-size:28px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:4px;">
      {badge_label}
    </div>
  </div>
  <div style="color:#CCCCCC;font-size:13px;">{badge_note}</div>
</div>
""", unsafe_allow_html=True)

    # ── Per-metric breakdown ──────────────────────────────────────────────────
    def _metric_section(title, rates_3, d1, d2, status, unit='%'):
        """Render a Code 33 metric row with 3 quarters + 2 deltas."""
        sc = {'green': GREEN, 'yellow': YELLOW, 'red': RED, 'insufficient': GRAY}[status]

        if len(rates_3) < 3:
            q_cells = '<td colspan="5" style="text-align:center;color:#555;padding:8px;">Insufficient data</td>'
        else:
            g1, g2, g3 = rates_3[-3], rates_3[-2], rates_3[-1]
            q_cells = f'''
<td style="text-align:right;padding:6px 10px;">{_rate_badge(g1)}</td>
<td style="text-align:right;padding:6px 10px;color:{GRAY};font-size:11px;">{_delta_badge(d1)}</td>
<td style="text-align:right;padding:6px 10px;">{_rate_badge(g2)}</td>
<td style="text-align:right;padding:6px 10px;color:{GRAY};font-size:11px;">{_delta_badge(d2)}</td>
<td style="text-align:right;padding:6px 10px;">{_rate_badge(g3)}</td>'''

        status_cell = f'<td style="text-align:center;padding:6px 10px;color:{sc};font-weight:bold;font-size:11px;">{status.upper()}</td>'

        return f'''
<tr style="border-bottom:1px solid #222;">
  <td style="padding:6px 10px;font-weight:bold;white-space:nowrap;">{title}</td>
  {q_cells}
  {status_cell}
</tr>'''

    hdr_gray = f'style="text-align:right;padding:6px 10px;color:{GRAY};font-size:10px;letter-spacing:1px;"'
    table_html = f'''
<div style="overflow-x:auto;margin-bottom:16px;">
<table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">
<thead>
<tr style="border-bottom:1px solid #333;">
  <th style="text-align:left;padding:6px 10px;color:{GRAY};font-size:10px;">METRIC</th>
  <th {hdr_gray}>Q-2 Rate</th>
  <th {hdr_gray}>Δ pp</th>
  <th {hdr_gray}>Q-1 Rate</th>
  <th {hdr_gray}>Δ pp</th>
  <th {hdr_gray}>Q0 Rate</th>
  <th style="text-align:center;padding:6px 10px;color:{GRAY};font-size:10px;">STATUS</th>
</tr>
</thead>
<tbody>
{_metric_section("EPS Growth YoY",      eps_last3, eps_d1, eps_d2, eps_status)}
{_metric_section("Revenue Growth YoY",  rev_last3, rev_d1, rev_d2, rev_status)}
{_metric_section("Net Profit Margin",   mgn_last3, mgn_d1, mgn_d2, mgn_status, unit='%')}
</tbody>
</table>
</div>'''
    st.markdown(table_html, unsafe_allow_html=True)

    # ── Legend & Minervini note ───────────────────────────────────────────────
    st.markdown(f"""
<div style="background:{BG};border-left:3px solid {YELLOW};border-radius:4px;
            padding:12px 16px;margin-top:8px;font-size:12px;color:#CCCCCC;line-height:1.7;">
  <b style="color:{YELLOW};">LEGEND</b>&nbsp;&nbsp;
  <span style="color:{GREEN};">GREEN RATE</span> = positive growth/margin &nbsp;|&nbsp;
  <span style="color:{RED};">RED RATE</span> = negative growth/margin &nbsp;|&nbsp;
  <span style="color:{GREEN};">▲ delta</span> = accelerating &nbsp;|&nbsp;
  <span style="color:{RED};">▼ delta</span> = decelerating (any negative delta = <b style="color:{RED};">RED</b>)<br>
  <br>
  <b style="color:{YELLOW};">Minervini:</b>
  "A shrinking delta signals institutional selling even at high growth rates.
  Dell peaked when EPS growth decelerated from 80% to 65% to 28% — each rate still high,
  but the deceleration confirmed distribution was underway."
  Code 33 is broken the moment ANY metric decelerates — even if the growth rate remains elevated.
</div>
""", unsafe_allow_html=True)

    # Rules summary
    with st.expander("Code 33 Rules (Minervini)", expanded=False):
        st.markdown(f"""
**Three metrics must ALL accelerate simultaneously for 3 consecutive quarters:**
1. **EPS Growth YoY%** — growth rate must increase Q-over-Q (positive delta)
2. **Revenue Growth YoY%** — growth rate must increase Q-over-Q (positive delta)
3. **Net Profit Margin** — margin itself must expand Q-over-Q (positive delta)

**Status determination (strict):**
- <span style="color:{GREEN}">**ACTIVE (Green)**</span> — All 3 metrics: both deltas positive AND second delta ≥ first delta
- <span style="color:{YELLOW}">**AT RISK (Yellow)**</span> — All 3 metrics still positive, but at least one has a shrinking (smaller positive) delta
- <span style="color:{RED}">**BROKEN (Red)**</span> — ANY metric has ANY negative delta (deceleration), regardless of absolute growth level

**Critical:** EPS growth 80% → 65% → 28% = **RED** (deceleration = Code 33 broken)
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — NEWS
# ════════════════════════════════════════════════════════════════════════════════
with tab5:
    col_title, col_refresh = st.columns([3, 1])
    with col_title:
        st.markdown("### News Feed")
    with col_refresh:
        if st.button("Refresh News", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    news_items = fetch_stock_news(ticker)

    if news_items:
        for item in news_items:
            title     = item.get('title', '')
            source    = item.get('source', '')
            published = item.get('published', '')
            link      = item.get('link', '')

            link_html = (f'<a href="{link}" target="_blank" style="color:{GREEN};text-decoration:none;">'
                         f'{title}</a>') if link else f'<span style="color:#CCCCCC;">{title}</span>'

            st.markdown(f"""
<div style="background:{BG};border:1px solid #222;border-radius:6px;
            padding:10px 14px;margin-bottom:8px;">
  <div style="font-size:13px;line-height:1.5;margin-bottom:4px;">{link_html}</div>
  <div style="font-size:11px;color:{GRAY};font-family:monospace;">
    {source} &nbsp;·&nbsp; {published}
  </div>
</div>""", unsafe_allow_html=True)
    else:
        st.info(f"No recent news found for {ticker}. Check back soon or verify the ticker.")

    st.caption(f"Auto-refreshes every 5 minutes · Sources: Finnhub + Alpaca · Last loaded: {datetime.utcnow().strftime('%H:%M UTC')}")
