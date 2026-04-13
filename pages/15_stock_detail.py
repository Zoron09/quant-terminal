"""
pages/15_stock_detail.py
Stock Detail — header, OHLC, price chart, 5 tabs.
Per CLAUDE.md Section 7. SEC EDGAR primary, yfinance fallback.
Column order: oldest LEFT, newest RIGHT throughout.
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
st.set_page_config(page_title="Stock Detail · Quant Terminal", page_icon="📋", layout="wide")

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

# ── Small utilities ───────────────────────────────────────────────────────────

def _nan(v):
    if v is None: return True
    try: return isinstance(v, float) and np.isnan(v)
    except Exception: return False

def _sf(v, default=None):
    if _nan(v): return default
    try: return float(v)
    except Exception: return default

def _time_ago(ts) -> str:
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.utcfromtimestamp(ts)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', ''))
        else:
            dt = ts
        diff = datetime.utcnow() - dt
        if diff.days >= 1: return f"{diff.days}d ago"
        h = diff.seconds // 3600
        if h >= 1: return f"{h}h ago"
        return f"{diff.seconds // 60}m ago"
    except Exception:
        return ''

def _fmt_cell(val, is_pct=False, already_pct=False):
    if _nan(val): return '<span style="color:#555">—</span>'
    try:
        v = float(val)
        if is_pct:
            txt = f"{v:.1f}%" if already_pct else f"{v*100:.1f}%"
            c   = GREEN if v > 0 else (RED if v < 0 else '#FFFFFF')
            return f'<span style="color:{c}">{txt}</span>'
        neg = v < 0; av = abs(v)
        if   av >= 1e12: s = f"{av/1e12:.2f}T"
        elif av >= 1e9:  s = f"{av/1e9:.2f}B"
        elif av >= 1e6:  s = f"{av/1e6:.1f}M"
        elif av >= 1e3:  s = f"{av/1e3:.1f}K"
        else:            s = f"{av:.2f}"
        return f'<span style="color:{RED}">({s})</span>' if neg else s
    except Exception:
        return '<span style="color:#555">—</span>'

def _growth_cell(curr, prev):
    """Compute % change curr vs prev. Show — if either missing or prev==0."""
    if _nan(curr) or _nan(prev) or prev == 0: return '<span style="color:#555">—</span>'
    try:
        g = (float(curr) - float(prev)) / abs(float(prev)) * 100
        c = GREEN if g >= 0 else RED
        return f'<span style="color:{c};font-size:11px;">{"+" if g>=0 else ""}{g:.1f}%</span>'
    except Exception:
        return '<span style="color:#555">—</span>'

def _pct_cell(num, denom):
    """Compute num/denom*100 and format as colored %."""
    n, d = _sf(num), _sf(denom)
    if n is None or d is None or d == 0: return '<span style="color:#555">—</span>'
    v = n / d * 100
    c = GREEN if v > 0 else (RED if v < 0 else '#FFFFFF')
    return f'<span style="color:{c}">{v:.1f}%</span>'

# ── SEC EDGAR ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_edgar_facts(ticker: str) -> dict | None:
    if '.' in ticker: return None
    cik = get_cik(ticker)
    if not cik: return None
    try:
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
                         headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def _edgar_series(facts: dict | None, concepts: list, unit: str = 'USD',
                  quarterly: bool = True, balance: bool = False) -> dict:
    """Returns {end_date: float} sorted ascending (oldest first), max 8 most recent entries."""
    if not facts: return {}
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    for concept in concepts:
        entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
        if not entries: continue
        # Filter by form type — consistent across all companies (no frame label dependency)
        # Balance sheet quarterly uses 10-Q same as income statement
        if quarterly or balance:
            filtered = [e for e in entries if e.get('form') == '10-Q']
        else:
            filtered = [e for e in entries if e.get('form') == '10-K']
        if len(filtered) < 3: continue
        by_end: dict = {}
        for e in filtered:
            end = e.get('end', '')
            if not end: continue
            if end not in by_end or e.get('filed', '') > by_end[end].get('filed', ''):
                by_end[end] = e
        if len(by_end) >= 3:
            sorted_items = sorted(by_end.items())
            recent_8 = sorted_items[-8:]   # cap at 8 most recent to avoid 2008-era data
            return {end: float(v['val']) for end, v in recent_8}
    return {}

# ── Code 33 data fetcher (yfinance only) ─────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_code33_data(ticker: str) -> dict:
    """
    Fetch raw quarterly data for Code 33 using yfinance ONLY.
    Needs ≥9 raw quarters to compute 5 YoY rates (index i vs i-4, for i=4..8).
    Returns {'eps': [...], 'rev': [...], 'ni': [...], 'sources': {...}}
    Values are floats oldest→newest (ascending). Empty list = insufficient data.
    """
    sources = {}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        q = t.quarterly_financials
        if q is None or not isinstance(q, pd.DataFrame) or q.empty:
            return {'eps': [], 'rev': [], 'ni': [], 'sources': sources}

        # Sort columns ascending: oldest leftmost
        q = q[sorted(q.columns)]

        def _extract(keys):
            for k in keys:
                if k in q.index:
                    return [_sf(q.loc[k, c]) for c in q.columns]
            return []

        eps = _extract(['Diluted EPS', 'Basic EPS', 'Earnings Per Share'])
        rev = _extract(['Total Revenue', 'Revenue'])
        ni  = _extract(['Net Income', 'Net Income Common Stockholders'])

        sources['eps'] = 'yfinance'
        sources['rev'] = 'yfinance'
        sources['ni']  = 'yfinance'

        # Need ≥9 raw quarters to produce ≥5 YoY rates (i=4..8)
        if len(eps) < 9: eps = []
        if len(rev) < 9: rev = []
        if len(ni)  < 9: ni  = []

    except Exception:
        eps = rev = ni = []
        sources = {}

    return {'eps': eps, 'rev': rev, 'ni': ni, 'sources': sources}

# ── Financial statements (EDGAR primary, yfinance fallback) ───────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_edgar_financials(ticker: str) -> dict:
    """
    Returns {income_q, income_a, balance_q, balance_a, cf_q, cf_a}.
    DataFrames: rows=metrics, cols=dates ASCENDING (oldest first = LEFT).
    """
    facts = get_edgar_facts(ticker)
    yf    = get_financials(ticker)

    def _ts(series: dict) -> pd.Series:
        return pd.Series({pd.Timestamp(k): v for k, v in series.items()})

    def _edgar_df(concept_rows, quarterly, balance=False):
        try:
            data = {}
            for name, concepts, _ in concept_rows:
                s = _edgar_series(facts, concepts, quarterly=quarterly, balance=balance)
                if s: data[name] = _ts(s)
            if not data: return None
            df = pd.DataFrame(data).T
            df = df.sort_index(axis=1, ascending=True)   # oldest LEFT
            return df
        except Exception:
            return None

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
            if len(result) == 0: return pd.DataFrame()
            out = pd.DataFrame(result).T
            out = out.sort_index(axis=1, ascending=True)  # oldest LEFT
            return out
        except Exception:
            return pd.DataFrame()

    IS_CONCEPTS = [
        ('Revenue',           ['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax'],
                              ['Total Revenue','Revenue']),
        ('Cost of Revenue',   ['CostOfRevenue','CostOfGoodsAndServicesSold'],
                              ['Cost Of Revenue','Cost Of Goods Sold']),
        ('Gross Profit',      ['GrossProfit'],
                              ['Gross Profit']),
        ('R&D',               ['ResearchAndDevelopmentExpense'],
                              ['Research And Development','Research And Development Expenses']),
        ('SG&A',              ['SellingGeneralAndAdministrativeExpense'],
                              ['Selling General And Administration','Selling General Administrative']),
        ('Operating Income',  ['OperatingIncomeLoss'],
                              ['Operating Income','EBIT']),
        ('D&A',               ['DepreciationDepletionAndAmortization','DepreciationAndAmortization'],
                              ['Depreciation And Amortization','Depreciation Amortization Depletion']),
        ('Interest Expense',  ['InterestExpense','InterestAndDebtExpense'],
                              ['Interest Expense']),
        ('Pretax Income',     ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'],
                              ['Pretax Income','Earnings Before Tax']),
        ('Tax Expense',       ['IncomeTaxExpenseBenefit'],
                              ['Tax Provision','Income Tax Expense']),
        ('Net Income',        ['NetIncomeLoss'],
                              ['Net Income','Net Income Common Stockholders']),
        ('EPS Diluted',       ['EarningsPerShareDiluted'],
                              ['Diluted EPS']),
        ('EPS Basic',         ['EarningsPerShareBasic'],
                              ['Basic EPS']),
    ]
    BS_CONCEPTS = [
        ('Cash & Equivalents',         ['CashAndCashEquivalentsAtCarryingValue','CashCashEquivalentsAndShortTermInvestments'],
                                       ['Cash And Cash Equivalents','Cash Financial']),
        ('Short-term Investments',     ['ShortTermInvestments','AvailableForSaleSecuritiesCurrent'],
                                       ['Other Short Term Investments','Short Term Investments']),
        ('Accounts Receivable',        ['AccountsReceivableNetCurrent'],
                                       ['Net Receivables','Accounts Receivable']),
        ('Inventory',                  ['InventoryNet'],
                                       ['Inventory']),
        ('Total Current Assets',       ['AssetsCurrent'],
                                       ['Current Assets','Total Current Assets']),
        ('PP&E',                       ['PropertyPlantAndEquipmentNet'],
                                       ['Net PPE','Property Plant And Equipment Net']),
        ('Goodwill',                   ['Goodwill'],
                                       ['Goodwill']),
        ('Intangibles',                ['FiniteLivedIntangibleAssetsNet','IndefiniteLivedIntangibleAssetsExcludingGoodwill'],
                                       ['Other Intangible Assets','Intangible Assets']),
        ('Total Assets',               ['Assets'],
                                       ['Total Assets']),
        ('Accounts Payable',           ['AccountsPayableCurrent'],
                                       ['Accounts Payable']),
        ('Total Current Liabilities',  ['LiabilitiesCurrent'],
                                       ['Current Liabilities','Total Current Liabilities']),
        ('Long-term Debt',             ['LongTermDebt','LongTermDebtNoncurrent'],
                                       ['Long Term Debt','Long Term Debt And Capital Lease Obligation']),
        ('Total Liabilities',          ['Liabilities'],
                                       ['Total Liabilities Net Minority Interest','Total Liabilities']),
        ('Total Equity',               ['StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
                                       ['Stockholders Equity','Common Stock Equity']),
    ]
    CF_CONCEPTS = [
        ('Operating Cash Flow',  ['NetCashProvidedByUsedInOperatingActivities'],
                                 ['Operating Cash Flow']),
        ('Capital Expenditure',  ['PaymentsToAcquirePropertyPlantAndEquipment'],
                                 ['Capital Expenditure']),
        ('Investing Activities', ['NetCashProvidedByUsedInInvestingActivities'],
                                 ['Investing Cash Flow','Net Cash Used In Investing Activities']),
        ('Share Buybacks',       ['PaymentsForRepurchaseOfCommonStock'],
                                 ['Repurchase Of Capital Stock']),
        ('Dividends Paid',       ['PaymentsOfDividends','PaymentsOfDividendsCommonStock'],
                                 ['Payment Of Dividends','Cash Dividends Paid']),
        ('Financing Activities', ['NetCashProvidedByUsedInFinancingActivities'],
                                 ['Financing Cash Flow','Net Cash Used In Financing Activities']),
        ('Net Change in Cash',   ['CashCashEquivalentsAndRestrictedCashPeriodIncreaseDecreaseIncludingExchangeRateEffect',
                                   'CashAndCashEquivalentsPeriodIncreaseDecrease'],
                                 ['Changes In Cash','Net Change In Cash']),
    ]

    out = {}
    for period, quarterly in [('q', True), ('a', False)]:
        yf_sfx = 'quarterly' if quarterly else 'annual'

        e_is = _edgar_df(IS_CONCEPTS, quarterly=quarterly)
        out[f'income_{period}'] = e_is if e_is is not None and len(e_is.columns) >= 3 \
            else _yf_df(f'income_{yf_sfx}', IS_CONCEPTS)

        e_bs = _edgar_df(BS_CONCEPTS, quarterly=quarterly, balance=True)
        out[f'balance_{period}'] = e_bs if e_bs is not None and len(e_bs.columns) >= 3 \
            else _yf_df(f'balance_{yf_sfx}', BS_CONCEPTS)

        e_cf = _edgar_df(CF_CONCEPTS, quarterly=quarterly)
        out[f'cf_{period}'] = e_cf if e_cf is not None and len(e_cf.columns) >= 3 \
            else _yf_df(f'cashflow_{yf_sfx}', CF_CONCEPTS)

    return out

# ── News ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_stock_news(ticker: str) -> list:
    items = []; seen: set = set()
    clean = ticker.upper().split('.')[0]
    if _HAS_FINNHUB:
        today = datetime.now().strftime('%Y-%m-%d')
        week  = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        try:
            r = requests.get('https://finnhub.io/api/v1/company-news',
                             params={'symbol': clean, 'from': week, 'to': today, 'token': FINNHUB_KEY}, timeout=8)
            for art in r.json():
                h = (art.get('headline') or '').strip()
                if h and h not in seen:
                    seen.add(h)
                    items.append({'title': h, 'source': art.get('source','Finnhub'),
                                  'published': _time_ago(art.get('datetime')), 'link': art.get('url','')})
        except Exception:
            pass
    try:
        if _HAS_ALPACA and ALPACA_KEY:
            r = requests.get('https://data.alpaca.markets/v1beta1/news',
                             params={'symbols': clean, 'limit': 30, 'sort': 'desc', 'include_content': 'false'},
                             auth=(ALPACA_KEY, ALPACA_SECRET), timeout=8)
            for art in r.json().get('news', []):
                h = (art.get('headline') or '').strip()
                if h and h not in seen:
                    seen.add(h)
                    items.append({'title': h, 'source': art.get('source','Alpaca'),
                                  'published': _time_ago(art.get('created_at') or art.get('updated_at','')),
                                  'link': art.get('url','')})
    except Exception:
        pass
    return items[:50]

# ── Financial table renderer ──────────────────────────────────────────────────
# Columns are ASCENDING (oldest=left, newest=right).
# Growth for col[i] = change vs col[i-1]; col[0] shows "—".

def _render_fin_table(df: pd.DataFrame, rows_spec: list, title: str,
                      chart_metric: str | None = None, chart_type: str = 'Bar'):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning(f"{title}: Data unavailable.")
        return

    cols_all  = list(df.columns)[:8]       # oldest first (ascending sort)
    date_strs = [str(c)[:7] for c in cols_all]  # e.g. 2024-03

    # ── Mini chart ──
    if chart_metric and chart_metric in df.index and len(cols_all) > 1:
        vals = [_sf(df.loc[chart_metric, c]) for c in cols_all]  # already oldest→newest
        if any(v is not None for v in vals):
            fig = go.Figure()
            if chart_type == 'Bar':
                colors = [GREEN if (v or 0) >= 0 else RED for v in vals]
                fig.add_trace(go.Bar(x=date_strs, y=vals, marker_color=colors,
                                     text=[_fmt_cell(v) if v is not None else '' for v in vals],
                                     textposition='outside', textfont_color='white'))
            else:
                fig.add_trace(go.Scatter(x=date_strs, y=vals,
                                         line=dict(color=GREEN, width=2),
                                         fill='tozeroy', fillcolor='rgba(0,255,65,0.06)'))
            fig.update_layout(paper_bgcolor=DARK, plot_bgcolor=BG, height=160,
                              margin=dict(t=5,b=5,l=5,r=5),
                              yaxis=dict(gridcolor='#222', color=GRAY, tickfont_size=9),
                              xaxis=dict(color=GRAY, tickfont_size=9),
                              font=dict(color='white', family='Courier New'),
                              showlegend=False,
                              title=dict(text=chart_metric, font=dict(color=GRAY, size=11)))
            st.plotly_chart(fig, use_container_width=True)

    # ── HTML table ──
    hcols = ''.join(f'<th style="text-align:right;color:{GRAY};font-size:11px;padding:4px 8px;">{d}</th>'
                    for d in date_strs)
    html  = (f'<div style="overflow-x:auto;margin-bottom:20px;">'
             f'<table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">'
             f'<thead><tr>'
             f'<th style="text-align:left;color:{GRAY};font-size:11px;padding:4px 8px;min-width:180px;">{title}</th>'
             f'{hcols}</tr></thead><tbody>')

    def _row_vals(row_name):
        return [_sf(df.loc[row_name, c]) for c in cols_all]

    def _render_data_row(label, raw, bold=False, indent=False, is_pct=False):
        cells = []
        for i, v in enumerate(raw):
            if is_pct:
                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(v, is_pct=True, already_pct=True)}</td>')
            else:
                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(v)}</td>')
        lbl = ('&nbsp;&nbsp;' if indent else '') + label
        fw  = 'font-weight:bold;' if bold else ''
        return (f'<tr style="border-top:1px solid #1a1a1a;">'
                f'<td style="padding:4px 8px;{fw}">{lbl}</td>' + ''.join(cells) + '</tr>\n')

    def _render_growth_row(label, raw):
        """Growth: col[i] vs col[i-1]. col[0] → —."""
        cells = []
        for i, v in enumerate(raw):
            if i == 0:
                cells.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')
            else:
                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_growth_cell(raw[i], raw[i-1])}</td>')
        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'
        return (f'<tr style="border-top:1px solid #1a1a1a;">'
                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')

    def _render_margin_row(label, num_row, denom_row='Revenue'):
        if num_row not in df.index or denom_row not in df.index: return ''
        cells = []
        for c in cols_all:
            cells.append(f'<td style="text-align:right;padding:4px 8px;">'
                         f'{_pct_cell(df.loc[num_row, c], df.loc[denom_row, c])}</td>')
        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'
        return (f'<tr style="border-top:1px solid #1a1a1a;">'
                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')

    def _render_ratio_row(label, num_row, denom_row, negate_num=False):
        if num_row not in df.index or denom_row not in df.index: return ''
        cells = []
        for c in cols_all:
            n = _sf(df.loc[num_row, c]); d = _sf(df.loc[denom_row, c])
            if n is None or d is None or d == 0:
                cells.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')
            else:
                if negate_num: n = -n
                v = n / d
                c_color = GRAY
                cells.append(f'<td style="text-align:right;padding:4px 8px;color:{c_color}">{v:.2f}x</td>')
        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'
        return (f'<tr style="border-top:1px solid #1a1a1a;">'
                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')

    def _render_computed_row(label, row_fn):
        """row_fn(cols_all) -> list of formatted td strings."""
        try:
            cells = row_fn(cols_all)
            lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'
            return (f'<tr style="border-top:1px solid #1a1a1a;">'
                    f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')
        except Exception:
            return ''

    for row_name, row_type in rows_spec:
        if row_type == 'section_header':
            html += (f'<tr><td colspan="{len(cols_all)+1}" style="padding:8px 6px 2px 6px;'
                     f'color:{GRAY};font-size:10px;letter-spacing:1px;border-top:1px solid #222;">'
                     f'{row_name}</td></tr>\n')
            continue

        # ── Computed rows that don't need the metric in df.index ──
        if row_type == 'ebitda':
            def _ebitda_cells(cols):
                out = []
                for c in cols:
                    oi = _sf(df.loc['Operating Income', c]) if 'Operating Income' in df.index else None
                    da = _sf(df.loc['D&A', c]) if 'D&A' in df.index else None
                    if oi is not None and da is not None:
                        out.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(oi + abs(da))}</td>')
                    else:
                        out.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')
                return out
            html += _render_computed_row('EBITDA', _ebitda_cells)
            continue

        if row_type == 'free_cf':
            def _fcf_cells(cols):
                out = []
                for c in cols:
                    ocf = _sf(df.loc['Operating Cash Flow', c]) if 'Operating Cash Flow' in df.index else None
                    cx  = _sf(df.loc['Capital Expenditure', c]) if 'Capital Expenditure' in df.index else None
                    if ocf is not None and cx is not None:
                        out.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(ocf - abs(cx))}</td>')
                    else:
                        out.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')
                return out
            html += _render_computed_row('Free Cash Flow', _fcf_cells)
            continue

        if row_type == 'de_ratio':
            html += _render_ratio_row('Debt-to-Equity', 'Long-term Debt', 'Total Equity')
            continue

        if row_type == 'tax_rate':
            html += _render_margin_row('Tax Rate%', 'Tax Expense', 'Pretax Income')
            continue

        if row_type == 'gross_margin':
            html += _render_margin_row('Gross Margin%', 'Gross Profit', 'Revenue')
            continue

        if row_type == 'op_margin':
            html += _render_margin_row('Operating Margin%', 'Operating Income', 'Revenue')
            continue

        if row_type == 'net_margin':
            html += _render_margin_row('Net Margin%', 'Net Income', 'Revenue')
            continue

        # ── Rows that need the metric in df.index ──
        if row_name not in df.index:
            # Row not found — show blank row so structure stays intact
            cells = ''.join(f'<td style="text-align:right;padding:4px 8px;color:#555">N/A</td>' for _ in cols_all)
            lbl = ('&nbsp;&nbsp;' if row_type not in ('bold',) else '') + row_name
            html += (f'<tr style="border-top:1px solid #1a1a1a;opacity:0.5;">'
                     f'<td style="padding:4px 8px;">{lbl}</td>{cells}</tr>\n')
            continue

        raw = _row_vals(row_name)

        if row_type in ('bold', 'raw'):
            html += _render_data_row(row_name, raw, bold=(row_type == 'bold'))
        elif row_type == 'indent':
            html += _render_data_row(row_name, raw, indent=True)
        elif row_type == 'growth':
            html += _render_growth_row(f'{row_name} Growth%', raw)
        elif row_type == 'bold_growth':
            html += _render_data_row(row_name, raw, bold=True)
            html += _render_growth_row(f'{row_name} Growth%', raw)

    html += '</tbody></table></div>'
    st.markdown(html, unsafe_allow_html=True)

# ── Code 33 computation ───────────────────────────────────────────────────────

def _compute_yoy(vals: list) -> list:
    """YoY[i] = (vals[i] - vals[i-4]) / |vals[i-4]| * 100 for i >= 4.
    Rates beyond ±2000% are treated as data anomalies and returned as None."""
    rates = []
    for i in range(4, len(vals)):
        c, p = vals[i], vals[i - 4]
        if c is not None and p is not None and p != 0 and not _nan(c) and not _nan(p):
            rate = (float(c) - float(p)) / abs(float(p)) * 100
            rates.append(rate if abs(rate) <= 2000 else None)  # sanity clamp
        else:
            rates.append(None)
    return rates

def _margin_series(ni: list, rev: list) -> list:
    out = []
    for n, r in zip(ni, rev):
        if n is not None and r is not None and r != 0 and not _nan(n) and not _nan(r):
            out.append(float(n) / float(r) * 100)
        else:
            out.append(None)
    return out

def _last3(lst: list) -> list:
    valid = [v for v in lst if v is not None]
    return valid[-3:] if len(valid) >= 3 else []

def _c33_status(rates3: list) -> tuple:
    """(status, d1, d2) — GREEN/YELLOW/RED/insufficient."""
    if len(rates3) < 3: return 'insufficient', None, None
    g1, g2, g3 = rates3[-3], rates3[-2], rates3[-1]
    d1, d2 = g2 - g1, g3 - g2
    if d1 < 0 or d2 < 0: return 'red', d1, d2
    if d2 >= d1:          return 'green', d1, d2
    return 'yellow', d1, d2

def _dc(d):
    if d is None: return GRAY
    return GREEN if d > 0 else (RED if d < 0 else YELLOW)

def _rate_badge(r):
    if r is None: return f'<span style="color:{GRAY}">N/A</span>'
    c = GREEN if r > 0 else RED
    return f'<span style="color:{c};font-weight:bold;">{r:+.1f}%</span>'

def _delta_badge(d):
    if d is None: return f'<span style="color:{GRAY}">—</span>'
    c = _dc(d); arrow = '▲' if d > 0 else ('▼' if d < 0 else '■')
    return f'<span style="color:{c}">{arrow} {"+" if d>=0 else ""}{d:.1f} pp</span>'

# ── Analyst estimate fetch ────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_analyst_estimates(ticker: str) -> dict:
    """Forward EPS estimates. yfinance primary, Finnhub fallback."""
    result = {'rows': [], 'source': ''}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        ee = t.earnings_estimate
        if isinstance(ee, pd.DataFrame) and not ee.empty:
            label_map = {
                '0q': 'Current Quarter', '+1q': 'Next Quarter',
                '0y': 'Current Year',   '+1y': 'Next Year',
            }
            for idx in ee.index:
                label = label_map.get(str(idx), str(idx))
                avg    = _sf(ee.loc[idx, 'avg'])       if 'avg'             in ee.columns else None
                low    = _sf(ee.loc[idx, 'low'])       if 'low'             in ee.columns else None
                high   = _sf(ee.loc[idx, 'high'])      if 'high'            in ee.columns else None
                n_ana  = _sf(ee.loc[idx, 'numberOfAnalysts']) if 'numberOfAnalysts' in ee.columns else None
                yago   = _sf(ee.loc[idx, 'yearAgoEps']) if 'yearAgoEps'     in ee.columns else None
                growth = _sf(ee.loc[idx, 'growth'])    if 'growth'          in ee.columns else None
                result['rows'].append({
                    'label': label, 'avg': avg, 'low': low, 'high': high,
                    'n': n_ana, 'yago': yago, 'growth': growth,
                })
            result['source'] = 'yfinance'
            return result
    except Exception:
        pass
    # Finnhub fallback: basic financials has some forward data
    if _HAS_FINNHUB:
        try:
            bf = fh_basic_financials(ticker.upper())
            if isinstance(bf, dict):
                m = bf.get('metric', {})
                for label, key in [('EPS Forward', 'epsForwardTTM')]:
                    v = _sf(m.get(key))
                    if v: result['rows'].append({'label': label, 'avg': v})
                result['source'] = 'Finnhub'
        except Exception:
            pass
    return result

# ── Main page ─────────────────────────────────────────────────────────────────

ticker = render_sidebar()
st.markdown("## 📋 Stock Detail")

if not ticker:
    st.info("Enter a ticker symbol in the sidebar to begin.")
    st.stop()

is_us = '.' not in ticker and not ticker.startswith('^')

with st.spinner(f"Loading {ticker} …"):
    try:    info    = get_ticker_info(ticker)
    except: info    = {}
    try:    bars_3y = get_price_history(ticker, period='3y', interval='1d')
    except: bars_3y = pd.DataFrame()
    try:    snaps   = get_snapshots((ticker.upper(),)) if is_us and _HAS_ALPACA else {}
    except: snaps   = {}
    try:    fin     = get_edgar_financials(ticker)
    except: fin     = {}
    try:    yf_fin  = get_financials(ticker)
    except: yf_fin  = {}

snap = snaps.get(ticker.upper(), {}) if isinstance(snaps, dict) else {}

# ── Price ─────────────────────────────────────────────────────────────────────
price      = _sf(snap.get('price'))      or _sf(safe_get(info,'currentPrice')) or _sf(safe_get(info,'regularMarketPrice'))
prev_close = _sf(snap.get('prev_close')) or _sf(safe_get(info,'regularMarketPreviousClose'))
chg        = (price - prev_close) if (price is not None and prev_close is not None) else None
chg_pct    = (chg / prev_close * 100) if (chg is not None and prev_close is not None and prev_close != 0) else None

open_p = _sf(snap.get('open')) or _sf(safe_get(info,'open'))
high_p = _sf(snap.get('high')) or _sf(safe_get(info,'dayHigh'))
low_p  = _sf(snap.get('low'))  or _sf(safe_get(info,'dayLow'))
vol_p  = snap.get('volume')    or safe_get(info,'volume')

hi52 = lo52 = avg_vol = None
if bars_3y is not None and not bars_3y.empty:
    last_252 = bars_3y.tail(252)
    hi52 = _sf(last_252['High'].max()); lo52 = _sf(last_252['Low'].min())
    avg_vol = _sf(bars_3y['Volume'].tail(50).mean())
hi52    = hi52    or _sf(safe_get(info,'fiftyTwoWeekHigh'))
lo52    = lo52    or _sf(safe_get(info,'fiftyTwoWeekLow'))
avg_vol = avg_vol or _sf(safe_get(info,'averageVolume'))

name     = safe_get(info,'longName') or safe_get(info,'shortName') or ticker
exchange = safe_get(info,'exchange') or safe_get(info,'market') or ''
sector   = safe_get(info,'sector') or ''

# ── Header ────────────────────────────────────────────────────────────────────
chg_color = GREEN if (chg is not None and chg >= 0) else RED
price_str = f"${price:,.2f}" if price else "—"
chg_str   = (f"{'+'if chg>=0 else ''}{chg:.2f} ({chg_pct:+.2f}%)"
             if chg is not None and chg_pct is not None else "—")

st.markdown(f"""
<div style="background:{BG};border:1px solid #333;border-radius:8px;padding:20px 24px;margin-bottom:12px;">
  <div style="color:{GRAY};font-size:12px;font-family:monospace;letter-spacing:1px;">
    {ticker.upper()} &nbsp;·&nbsp; {exchange} &nbsp;·&nbsp; {sector}
  </div>
  <div style="color:#FFF;font-size:20px;font-weight:bold;margin:4px 0;">{name}</div>
  <div style="display:flex;align-items:baseline;gap:16px;margin-top:6px;">
    <span style="color:#FFF;font-size:36px;font-weight:bold;font-family:'Courier New',monospace;">{price_str}</span>
    <span style="color:{chg_color};font-size:18px;font-weight:bold;font-family:monospace;">{chg_str}</span>
  </div>
</div>""", unsafe_allow_html=True)

# ── OHLC Bar ──────────────────────────────────────────────────────────────────
def _oc(label, val, fn=None):
    v = fn(val) if fn and val else (f"${val:,.2f}" if val else "—")
    return (f'<div style="text-align:center;padding:8px 12px;">'
            f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'
            f'<div style="color:#FFF;font-size:14px;font-weight:bold;font-family:monospace;margin-top:3px;">{v}</div></div>')

sep = '<div style="width:1px;background:#333;margin:8px 0;"></div>'
st.markdown(f'''
<div style="background:{BG};border:1px solid #333;border-radius:6px;display:flex;flex-wrap:wrap;margin-bottom:16px;">
  {_oc("OPEN",open_p)}{sep}{_oc("HIGH",high_p)}{sep}{_oc("LOW",low_p)}{sep}
  {_oc("PREV CLOSE",prev_close)}{sep}{_oc("VOLUME",vol_p,fmt_volume)}{sep}
  {_oc("AVG VOL(50D)",avg_vol,fmt_volume)}{sep}{_oc("52W HIGH",hi52)}{sep}{_oc("52W LOW",lo52)}
</div>''', unsafe_allow_html=True)

# ── Price Chart ───────────────────────────────────────────────────────────────
range_opts = {'1D':1,'1W':7,'1M':30,'3M':90,'6M':180,'1Y':365}
sel_range  = st.radio('Range', list(range_opts.keys()), horizontal=True, index=3, label_visibility='collapsed')

chart_df = pd.DataFrame()
if bars_3y is not None and not bars_3y.empty:
    cutoff   = bars_3y.index[-1] - timedelta(days=range_opts[sel_range])
    chart_df = bars_3y[bars_3y.index >= cutoff].copy()

if not chart_df.empty:
    fp = _sf(chart_df['Close'].iloc[0]); lp = _sf(chart_df['Close'].iloc[-1])
    lc = GREEN if (fp and lp and lp >= fp) else RED
    rgb = ','.join(str(int(lc.lstrip('#')[i:i+2], 16)) for i in (0, 2, 4))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Close'],
                             line=dict(color=lc, width=2),
                             fill='tozeroy', fillcolor=f'rgba({rgb},0.08)',
                             hovertemplate='%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'))
    fig.update_layout(paper_bgcolor=DARK, plot_bgcolor=BG, height=320,
                      margin=dict(t=10,b=10,l=10,r=10),
                      yaxis=dict(gridcolor='#222', color=GRAY, tickprefix='$'),
                      xaxis=dict(color=GRAY, rangeslider=dict(visible=False)),
                      font=dict(color='white', family='Courier New'),
                      showlegend=False, hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("No price history available.")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview","Financials","Earnings & Estimates","Code 33","News"])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    try:
        fhm = (fh_basic_financials(ticker.upper()) or {}).get('metric', {}) if _HAS_FINNHUB and is_us else {}
    except Exception:
        fhm = {}

    mkt_cap   = _sf(safe_get(info,'marketCap'))
    pe_ttm    = _sf(safe_get(info,'trailingPE'))     or _sf(fhm.get('peTTM'))
    pe_fwd    = _sf(safe_get(info,'forwardPE'))      or _sf(fhm.get('peForwardTTM'))
    eps_ttm   = _sf(safe_get(info,'trailingEps'))    or _sf(fhm.get('epsTTM'))
    rev_ttm   = _sf(safe_get(info,'totalRevenue'))   or _sf(fhm.get('revenueTTM'))
    gross_mgn = _sf(safe_get(info,'grossMargins'))   or _sf(fhm.get('grossMarginTTM'))
    net_mgn   = _sf(safe_get(info,'profitMargins'))  or _sf(fhm.get('netProfitMarginTTM'))
    beta      = _sf(safe_get(info,'beta'))           or _sf(fhm.get('beta'))
    roe       = _sf(safe_get(info,'returnOnEquity')) or _sf(fhm.get('roeTTM'))
    de_ratio  = _sf(safe_get(info,'debtToEquity'))   or _sf(fhm.get('totalDebt/totalEquityAnnual'))
    div_yield = _sf(safe_get(info,'dividendYield'))  or _sf(fhm.get('dividendYieldIndicatedAnnual'))
    float_sh  = _sf(safe_get(info,'floatShares'))

    def _card(label, value, fmt='num', suffix='', prefix=''):
        if value is None or _nan(value): disp, col = "N/A", GRAY
        elif fmt == 'large':   disp, col = fmt_large_number(value), '#FFF'
        elif fmt == 'pct':
            disp = f"{value*100:.1f}%"
            col  = GREEN if value > 0 else (RED if value < 0 else '#FFF')
        elif fmt == 'price':   disp, col = f"${value:,.2f}", '#FFF'
        elif fmt == 'shares':  disp, col = fmt_large_number(value, symbol=''), '#FFF'
        else:                  disp, col = f"{prefix}{value:,.2f}{suffix}", '#FFF'
        return (f'<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">'
                f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'
                f'<div style="color:{col};font-size:20px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{disp}</div></div>')

    r1a,r1b,r1c,r1d = st.columns(4)
    r1a.markdown(_card("MARKET CAP",    mkt_cap,  fmt='large'), unsafe_allow_html=True)
    r1b.markdown(_card("P/E TTM",       pe_ttm,   suffix='x'),  unsafe_allow_html=True)
    r1c.markdown(_card("P/E FORWARD",   pe_fwd,   suffix='x'),  unsafe_allow_html=True)
    r1d.markdown(_card("EPS TTM",       eps_ttm,  fmt='price'), unsafe_allow_html=True)
    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)

    r2a,r2b,r2c,r2d = st.columns(4)
    r2a.markdown(_card("REVENUE TTM",   rev_ttm,  fmt='large'), unsafe_allow_html=True)
    r2b.markdown(_card("GROSS MARGIN",  gross_mgn,fmt='pct'),   unsafe_allow_html=True)
    r2c.markdown(_card("NET MARGIN",    net_mgn,  fmt='pct'),   unsafe_allow_html=True)
    r2d.markdown(_card("BETA",          beta,     suffix=''),   unsafe_allow_html=True)
    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)

    r3a,r3b,r3c,r3d = st.columns(4)
    r3a.markdown(_card("ROE",           roe,      fmt='pct'),   unsafe_allow_html=True)
    de_disp = (de_ratio/100 if de_ratio and de_ratio > 10 else de_ratio)
    r3b.markdown(_card("DEBT/EQUITY",   de_disp,  suffix='x'),  unsafe_allow_html=True)
    r3c.markdown(_card("DIV YIELD",     div_yield,fmt='pct'),   unsafe_allow_html=True)
    r3d.markdown(_card("FLOAT SHARES",  float_sh, fmt='shares'),unsafe_allow_html=True)

    desc = safe_get(info,'longBusinessSummary') or ''
    if desc:
        st.markdown("<div style='margin:16px 0 4px 0'></div>", unsafe_allow_html=True)
        with st.expander("Company Description", expanded=False):
            st.markdown(f"<div style='color:#CCC;font-size:13px;line-height:1.6'>{desc}</div>",
                        unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — FINANCIALS
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    c1, c2 = st.columns(2)
    with c1: period_sel    = st.radio("Period", ["Quarterly","Annual"], horizontal=True)
    with c2: chart_type_sel= st.radio("Chart",  ["Bar","Line"],         horizontal=True)

    pk = 'q' if period_sel == 'Quarterly' else 'a'

    income_df  = fin.get(f'income_{pk}',  pd.DataFrame())
    balance_df = fin.get(f'balance_{pk}', pd.DataFrame())
    cf_df      = fin.get(f'cf_{pk}',      pd.DataFrame())

    # ── Income Statement ──────────────────────────────────────────────────────
    st.markdown(f"### Income Statement <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",
                unsafe_allow_html=True)
    IS_ROWS = [
        ('Revenue',          'bold_growth'),
        ('Cost of Revenue',  'indent'),
        ('Gross Profit',     'raw'),
        ('gross_margin',     'gross_margin'),
        ('R&D',              'indent'),
        ('SG&A',             'indent'),
        ('Operating Income', 'raw'),
        ('op_margin',        'op_margin'),
        ('EBITDA',           'ebitda'),
        ('D&A',              'indent'),
        ('Interest Expense', 'indent'),
        ('Pretax Income',    'raw'),
        ('Tax Expense',      'indent'),
        ('tax_rate',         'tax_rate'),
        ('Net Income',       'bold'),
        ('net_margin',       'net_margin'),
        ('EPS Diluted',      'bold_growth'),
        ('EPS Basic',        'raw'),
    ]
    _render_fin_table(income_df, IS_ROWS, "Income Statement", 'Revenue', chart_type_sel)

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    st.markdown(f"### Balance Sheet <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",
                unsafe_allow_html=True)
    BS_ROWS = [
        ('Cash & Equivalents',         'bold'),
        ('Short-term Investments',     'indent'),
        ('Accounts Receivable',        'indent'),
        ('Inventory',                  'indent'),
        ('Total Current Assets',       'raw'),
        ('PP&E',                       'indent'),
        ('Goodwill',                   'indent'),
        ('Intangibles',                'indent'),
        ('Total Assets',               'bold'),
        ('Accounts Payable',           'indent'),
        ('Total Current Liabilities',  'raw'),
        ('Long-term Debt',             'indent'),
        ('Total Liabilities',          'bold'),
        ('Total Equity',               'bold'),
        ('de_ratio',                   'de_ratio'),
    ]
    _render_fin_table(balance_df, BS_ROWS, "Balance Sheet", 'Total Assets', chart_type_sel)

    # ── Cash Flow ─────────────────────────────────────────────────────────────
    st.markdown(f"### Cash Flow <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",
                unsafe_allow_html=True)
    CF_ROWS = [
        ('Operating Cash Flow',  'bold'),
        ('Capital Expenditure',  'indent'),
        ('Free Cash Flow',       'free_cf'),
        ('Investing Activities', 'raw'),
        ('Share Buybacks',       'indent'),
        ('Dividends Paid',       'indent'),
        ('Financing Activities', 'raw'),
        ('Net Change in Cash',   'bold'),
    ]
    _render_fin_table(cf_df, CF_ROWS, "Cash Flow", 'Operating Cash Flow', chart_type_sel)
    st.caption("Primary: SEC EDGAR · Fallback: yfinance · Oldest column = LEFT")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — EARNINGS & ESTIMATES
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    try:
        surprises = fh_earnings_surprises(ticker.upper()) if _HAS_FINNHUB and is_us else None
    except Exception:
        surprises = None

    # Next earnings date + countdown
    next_date = next_countdown = None
    try:
        import yfinance as yf_mod
        cal = yf_mod.Ticker(ticker).calendar
        if isinstance(cal, dict):
            ed = cal.get('Earnings Date')
            if isinstance(ed, list) and ed:    next_date = str(ed[0])[:10]
            elif ed is not None:               next_date = str(ed)[:10]
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            try: next_date = str(cal.loc['Earnings Date'].iloc[0])[:10]
            except Exception: pass
        if next_date:
            nd = datetime.strptime(next_date, '%Y-%m-%d')
            diff = (nd - datetime.now()).days
            next_countdown = f"{diff}d" if diff >= 0 else "Passed"
    except Exception:
        pass

    # Beat rates (last 8Q)
    last_date = eps_beat_rate = rev_beat_rate = None
    if isinstance(surprises, list) and len(surprises) > 0:
        last_date = surprises[0].get('period', '')
        last8 = surprises[:8]
        eps_b = sum(1 for s in last8 if (_sf(s.get('surprisePercent')) or 0) > 0)
        eps_beat_rate = eps_b / len(last8) * 100 if len(last8) > 0 else None

    # ── 4 Insight cards ──────────────────────────────────────────────────────
    def _ic(label, val, sub='', color='#FFF'):
        return (f'<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">'
                f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'
                f'<div style="color:{color};font-size:18px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{val or "—"}</div>'
                f'{"<div style=color:"+GRAY+";font-size:11px;margin-top:2px>"+sub+"</div>" if sub else ""}'
                f'</div>')

    bc = GREEN if eps_beat_rate and eps_beat_rate >= 70 else (YELLOW if eps_beat_rate and eps_beat_rate >= 50 else RED)
    ic1,ic2,ic3,ic4 = st.columns(4)
    ic1.markdown(_ic("LAST REPORTED",      last_date or '—'), unsafe_allow_html=True)
    ic2.markdown(_ic("NEXT EARNINGS",      next_date or '—', sub=next_countdown or ''), unsafe_allow_html=True)
    ic3.markdown(_ic("EPS BEAT RATE (8Q)", f"{eps_beat_rate:.0f}%" if eps_beat_rate is not None else '—', color=bc), unsafe_allow_html=True)
    ic4.markdown(_ic("REV BEAT RATE (8Q)", "—"), unsafe_allow_html=True)

    st.markdown("<div style='margin:16px 0 8px 0'></div>", unsafe_allow_html=True)

    # ── Surprise table ───────────────────────────────────────────────────────
    if isinstance(surprises, list) and len(surprises) > 0:
        st.markdown(f"#### Earnings Surprise History")

        def _sv(v): # surprise value cell
            if v is None: return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
            return f'<td style="text-align:right;padding:6px 10px;">{v:.2f}</td>'
        def _sc(pct): # surprise % cell colored
            if pct is None: return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
            c = GREEN if pct > 0 else RED
            return f'<td style="text-align:right;padding:6px 10px;color:{c};font-weight:bold;">{pct:+.1f}%</td>'

        rows_html = ''
        for s in surprises[:12]:
            qtr     = s.get('period','')
            eps_est = _sf(s.get('estimate'))
            eps_act = _sf(s.get('actual'))
            eps_sur = _sf(s.get('surprisePercent'))
            rows_html += (f'<tr style="border-bottom:1px solid #1a1a1a;">'
                          f'<td style="padding:6px 10px;color:{GRAY};font-family:monospace;">{qtr}</td>'
                          f'{_sv(eps_est)}{_sv(eps_act)}{_sc(eps_sur)}'
                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'
                          f'</tr>')

        hg = f'color:{GRAY};font-size:11px;padding:6px 10px;text-align:right'
        st.markdown(
            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">'
            f'<thead style="background:{BG}"><tr>'
            f'<th style="color:{GRAY};font-size:11px;padding:6px 10px;text-align:left">Quarter</th>'
            f'<th style="{hg}">EPS Est</th><th style="{hg}">EPS Actual</th>'
            f'<th style="{hg}">EPS Surp%</th>'
            f'<th style="{hg}">Rev Est</th><th style="{hg}">Rev Actual</th>'
            f'<th style="{hg}">Rev Surp%</th>'
            f'</tr></thead><tbody>{rows_html}</tbody></table></div>',
            unsafe_allow_html=True)
    else:
        st.info("Earnings surprise data unavailable (Finnhub).")

    # ── Analyst forward estimates ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Analyst Forward EPS Estimates")
    try:
        est_data = get_analyst_estimates(ticker)
    except Exception:
        est_data = {'rows': [], 'source': ''}

    if est_data.get('rows'):
        eg = f'color:{GRAY};font-size:11px;padding:6px 12px;text-align:right'
        rows_e = ''
        for row in est_data['rows']:
            avg  = _sf(row.get('avg'))
            low  = _sf(row.get('low'))
            high = _sf(row.get('high'))
            n    = row.get('n')
            yago = _sf(row.get('yago'))
            grw  = _sf(row.get('growth'))
            def _ep(v): return f"${v:.2f}" if v is not None else "—"
            def _gp(v):
                if v is None: return "—"
                c = GREEN if v > 0 else RED
                return f'<span style="color:{c}">{v*100:+.1f}%</span>'
            rows_e += (f'<tr style="border-bottom:1px solid #1a1a1a">'
                       f'<td style="padding:6px 12px">{row.get("label","")}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{_ep(avg)}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{_ep(low)}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{_ep(high)}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{int(n) if n else "—"}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{_ep(yago)}</td>'
                       f'<td style="text-align:right;padding:6px 12px">{_gp(grw)}</td>'
                       f'</tr>')
        st.markdown(
            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px">'
            f'<thead style="background:{BG}"><tr>'
            f'<th style="color:{GRAY};font-size:11px;padding:6px 12px;text-align:left">Period</th>'
            f'<th style="{eg}">Avg EPS</th><th style="{eg}">Low</th><th style="{eg}">High</th>'
            f'<th style="{eg}">Analysts</th><th style="{eg}">Year-ago EPS</th><th style="{eg}">Growth%</th>'
            f'</tr></thead><tbody>{rows_e}</tbody></table></div>',
            unsafe_allow_html=True)
        st.caption(f"Source: {est_data.get('source','')}")
    else:
        st.info("Forward EPS estimates not available for this ticker.")

    st.caption("Surprise data: Finnhub · Estimates: yfinance / Finnhub")

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — CODE 33
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### Code 33 — Minervini Fundamental Acceleration")

    # ── Fetch data ────────────────────────────────────────────────────────────
    try:
        c33 = get_code33_data(ticker)
    except Exception:
        c33 = {'eps': [], 'rev': [], 'ni': [], 'sources': {}}

    eps_raw = c33.get('eps', [])
    rev_raw = c33.get('rev', [])
    ni_raw  = c33.get('ni',  [])
    sources = c33.get('sources', {})

    # ── Compute YoY growth rates ──────────────────────────────────────────────
    eps_yoy = _compute_yoy(eps_raw)
    rev_yoy = _compute_yoy(rev_raw)

    # Margin: align NI and Rev to same length
    mn = min(len(ni_raw), len(rev_raw))
    mgn_vals = _margin_series(ni_raw[:mn], rev_raw[:mn])

    # Get last 3 valid values from each series
    eps3 = _last3(eps_yoy)
    rev3 = _last3(rev_yoy)
    mgn3 = _last3(mgn_vals)

    eps_status, eps_d1, eps_d2 = _c33_status(eps3)
    rev_status, rev_d1, rev_d2 = _c33_status(rev3)
    mgn_status, mgn_d1, mgn_d2 = _c33_status(mgn3)

    statuses = [eps_status, rev_status, mgn_status]
    if 'insufficient' in statuses:          overall = 'insufficient'
    elif 'red'         in statuses:          overall = 'red'
    elif 'yellow'      in statuses:          overall = 'yellow'
    else:                                    overall = 'green'

    badge_map = {
        'green':        (GREEN,  'ACTIVE',        'All 3 metrics accelerating for 3+ consecutive quarters'),
        'yellow':       (YELLOW, 'AT RISK',       'Acceleration slowing — watch for deceleration'),
        'red':          (RED,    'BROKEN',         'Deceleration detected — Code 33 is NOT active'),
        'insufficient': (GRAY,   'INSUFFICIENT',  'Need ≥5 quarters of raw data to evaluate'),
    }
    bc, bl, bn = badge_map[overall]

    st.markdown(f"""
<div style="background:{BG};border:2px solid {bc};border-radius:8px;
            padding:14px 22px;margin-bottom:20px;display:flex;align-items:center;gap:20px;">
  <div>
    <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:2px;">CODE 33 STATUS</div>
    <div style="color:{bc};font-size:26px;font-weight:bold;font-family:'Courier New',monospace;margin-top:4px;">{bl}</div>
  </div>
  <div style="color:#CCC;font-size:13px;">{bn}</div>
</div>""", unsafe_allow_html=True)

    # ── 3 side-by-side cards ──────────────────────────────────────────────────
    def _c33_card(title, rates3, d1, d2, status, unit='%'):
        sc    = {'green': GREEN, 'yellow': YELLOW, 'red': RED, 'insufficient': GRAY}[status]
        sl    = {'green': 'ACTIVE', 'yellow': 'AT RISK', 'red': 'BROKEN', 'insufficient': 'INSUFFICIENT'}[status]
        bg    = {'green': '#0d2818', 'yellow': '#1a1500', 'red': '#2a0d0d', 'insufficient': '#1a1a1a'}[status]

        if len(rates3) < 3:
            body = f'<div style="color:{GRAY};padding:12px;text-align:center;">Insufficient data<br><span style="font-size:10px">Need ≥5 raw quarters</span></div>'
        else:
            g1, g2, g3 = rates3[-3], rates3[-2], rates3[-1]
            def _qrow(label, rate, delta=None, is_first=False):
                delta_html = '' if is_first else f'<div style="font-size:11px;margin-bottom:3px">{_delta_badge(delta)}</div>'
                return (f'<div style="padding:8px 0;border-bottom:1px solid #2a2a2a;">'
                        f'{delta_html}'
                        f'<div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<span style="color:{GRAY};font-size:11px;font-family:monospace">{label}</span>'
                        f'<span style="font-size:14px">{_rate_badge(rate)}</span></div></div>')
            body = (_qrow('Q-2 (oldest)', g1, is_first=True) +
                    _qrow('Q-1',          g2, delta=d1) +
                    _qrow('Q0 (latest)',  g3, delta=d2))

        return (f'<div style="background:{bg};border:2px solid {sc};border-radius:8px;padding:14px 16px;height:100%">'
                f'<div style="color:#FFF;font-size:13px;font-weight:bold;margin-bottom:8px">{title}</div>'
                f'{body}'
                f'<div style="margin-top:10px;text-align:center;background:{sc}22;border-radius:4px;padding:4px">'
                f'<span style="color:{sc};font-weight:bold;font-size:11px;font-family:monospace">{sl}</span></div>'
                f'</div>')

    card_col1, card_col2, card_col3 = st.columns(3)
    card_col1.markdown(_c33_card("EPS Growth YoY%",     eps3, eps_d1, eps_d2, eps_status), unsafe_allow_html=True)
    card_col2.markdown(_c33_card("Revenue Growth YoY%", rev3, rev_d1, rev_d2, rev_status), unsafe_allow_html=True)
    card_col3.markdown(_c33_card("Net Profit Margin",   mgn3, mgn_d1, mgn_d2, mgn_status, unit='%'), unsafe_allow_html=True)

    # ── Debug caption ──────────────────────────────────────────────────────────
    eps_n = len([v for v in eps_raw if v is not None])
    rev_n = len([v for v in rev_raw if v is not None])
    ni_n  = len([v for v in ni_raw  if v is not None])
    st.caption(
        f"Data — EPS: {eps_n}Q ({sources.get('eps','—')}) · "
        f"Revenue: {rev_n}Q ({sources.get('rev','—')}) · "
        f"Net Income: {ni_n}Q ({sources.get('ni','—')})"
    )

    # ── Minervini note ────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="background:{BG};border-left:3px solid {YELLOW};border-radius:4px;
            padding:12px 16px;margin-top:12px;font-size:12px;color:#CCC;line-height:1.7">
  <b style="color:{YELLOW}">Rules:</b>
  <span style="color:{GREEN}">GREEN rate</span> = positive &nbsp;|&nbsp;
  <span style="color:{RED}">RED rate</span> = negative &nbsp;|&nbsp;
  <span style="color:{GREEN}">▲ delta</span> = accelerating &nbsp;|&nbsp;
  <span style="color:{RED}">▼ delta</span> = decelerating → any negative Δ = <b style="color:{RED}">BROKEN</b><br>
  <b style="color:{YELLOW}">Minervini:</b> "Dell peaked when EPS growth decelerated from 80%→65%→28%.
  Each number was still high — but the shrinking delta confirmed institutional distribution was underway.
  Code 33 breaks the moment ANY metric decelerates, regardless of the absolute growth level."
</div>""", unsafe_allow_html=True)

    with st.expander("Code 33 Full Rules", expanded=False):
        st.markdown(f"""
**Three metrics must ALL simultaneously hold for 3 consecutive quarters:**

1. **EPS Growth YoY%** — rate must increase quarter-over-quarter (positive delta)
2. **Revenue Growth YoY%** — rate must increase quarter-over-quarter (positive delta)
3. **Net Profit Margin** — margin level must expand quarter-over-quarter (positive delta)

**Status:**
- <span style="color:{GREEN}">**ACTIVE**</span> — all 3: both deltas positive AND Δ2 ≥ Δ1
- <span style="color:{YELLOW}">**AT RISK**</span> — all 3 rates positive, but at least one Δ is shrinking (Δ2 < Δ1, both still positive)
- <span style="color:{RED}">**BROKEN**</span> — any metric has any negative delta
- EPS 80% → 65% → 28% = **BROKEN** (Δ=-15pp, Δ=-37pp — both negative)
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — NEWS
# ════════════════════════════════════════════════════════════════════════════════
with tab5:
    hdr_col, btn_col = st.columns([3, 1])
    with hdr_col: st.markdown("### News Feed")
    with btn_col:
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    try:
        news_items = fetch_stock_news(ticker)
    except Exception:
        news_items = []

    if news_items:
        for item in news_items:
            title = item.get('title',''); src = item.get('source','')
            pub   = item.get('published',''); link = item.get('link','')
            link_html = (f'<a href="{link}" target="_blank" style="color:{GREEN};text-decoration:none">{title}</a>'
                         if link else f'<span style="color:#CCC">{title}</span>')
            st.markdown(
                f'<div style="background:{BG};border:1px solid #222;border-radius:6px;'
                f'padding:10px 14px;margin-bottom:8px">'
                f'<div style="font-size:13px;line-height:1.5;margin-bottom:4px">{link_html}</div>'
                f'<div style="font-size:11px;color:{GRAY};font-family:monospace">{src} · {pub}</div></div>',
                unsafe_allow_html=True)
    else:
        st.info(f"No recent news for {ticker}. Check the ticker or try again later.")

    st.caption(f"Auto-refresh: 5 min cache · Sources: Finnhub + Alpaca · {datetime.now().strftime('%H:%M')}")
