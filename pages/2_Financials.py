import streamlit as st
import sys, os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_financials

st.set_page_config(page_title="Financials · Quant Terminal", page_icon="📊", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 📊 Financial Statements")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()


def fmt_fin_cell(val):
    """Format a single financial cell."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return '<span style="color:#444">—</span>'
    try:
        v = float(val)
        negative = v < 0
        av = abs(v)
        if av >= 1e9:
            s = f"{av/1e9:.2f}B"
        elif av >= 1e6:
            s = f"{av/1e6:.1f}M"
        elif av >= 1e3:
            s = f"{av/1e3:.1f}K"
        else:
            s = f"{av:.0f}"
        if negative:
            return f'<span style="color:#FF4444">({s})</span>'
        return s
    except Exception:
        return '<span style="color:#444">—</span>'


def growth_pct(curr, prev):
    try:
        if curr and prev and prev != 0 and not np.isnan(curr) and not np.isnan(prev):
            g = (curr - prev) / abs(prev) * 100
            c = '#00FF41' if g >= 0 else '#FF4444'
            sign = '+' if g >= 0 else ''
            return f'<span style="color:{c};font-size:11px;">{sign}{g:.1f}%</span>'
    except Exception:
        pass
    return '<span style="color:#444;font-size:11px;">—</span>'


def render_fin_table(df: pd.DataFrame, row_map: list):
    """
    df: yfinance financial DataFrame (rows=metrics, cols=dates, most-recent first)
    row_map: list of (display_name, [possible_yf_keys])
    """
    if df is None or df.empty:
        st.warning("Data not available.")
        return

    cols = list(df.columns)[:8]          # up to 8 periods
    date_labels = [str(c)[:10] for c in cols]

    # Build header
    header = '<th>Metric</th>' + ''.join(f'<th>{d}</th>' for d in date_labels)
    # optional: YoY growth col after each date except last
    rows_html = ''

    for display, keys in row_map:
        # Find the matching row
        row_data = None
        for k in keys:
            if k in df.index:
                row_data = df.loc[k]
                break

        cells = ''
        if row_data is not None:
            values = [row_data.get(c) if c in row_data.index else None for c in cols]
            for i, v in enumerate(values):
                cells += f'<td>{fmt_fin_cell(v)}</td>'
        else:
            cells = ''.join('<td><span style="color:#444">—</span></td>' for _ in cols)

        rows_html += f'<tr><td>{display}</td>{cells}</tr>'

        # Growth row
        if row_data is not None:
            values = [row_data.get(c) if c in row_data.index else None for c in cols]
            growth_cells = '<td style="color:#555;font-size:11px;">YoY Δ</td>'
            for i in range(len(cols)):
                if i < len(cols) - 1:
                    growth_cells += f'<td>{growth_pct(values[i], values[i+1])}</td>'
                else:
                    growth_cells += '<td>—</td>'
            rows_html += f'<tr class="growth-row">{growth_cells}</tr>'

    html = f"""
    <div style="overflow-x:auto;">
    <table class="fin-table">
      <thead><tr>{header}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ── Data ──────────────────────────────────────────────────────────────────────
with st.spinner(f"Loading financials for {ticker} …"):
    fins = get_financials(ticker)

view = st.radio("Period", ["Annual", "Quarterly"], horizontal=True)
annual = view == "Annual"

income_tab, balance_tab, cashflow_tab = st.tabs(
    ["📈 Income Statement", "🏦 Balance Sheet", "💵 Cash Flow"]
)

# ── INCOME STATEMENT ──────────────────────────────────────────────────────────
with income_tab:
    st.markdown('<div class="section-title">Income Statement</div>', unsafe_allow_html=True)
    df = fins.get('income_annual') if annual else fins.get('income_quarterly')
    income_rows = [
        ("Revenue",            ['Total Revenue', 'Revenue']),
        ("Cost of Revenue",    ['Cost Of Revenue', 'Cost of Revenue']),
        ("Gross Profit",       ['Gross Profit']),
        ("Operating Expenses", ['Total Operating Expenses', 'Operating Expense']),
        ("Operating Income",   ['Operating Income', 'Ebit']),
        ("Net Income",         ['Net Income', 'Net Income Common Stockholders']),
        ("EPS (Basic)",        ['Basic EPS', 'Basic Eps']),
        ("EPS (Diluted)",      ['Diluted EPS', 'Diluted Eps']),
    ]
    render_fin_table(df, income_rows)

# ── BALANCE SHEET ─────────────────────────────────────────────────────────────
with balance_tab:
    st.markdown('<div class="section-title">Balance Sheet</div>', unsafe_allow_html=True)
    df = fins.get('balance_annual') if annual else fins.get('balance_quarterly')
    bs_rows = [
        ("Total Assets",          ['Total Assets']),
        ("Total Liabilities",     ['Total Liabilities Net Minority Interest', 'Total Liabilities']),
        ("Total Equity",          ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity']),
        ("Cash & Equivalents",    ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments']),
        ("Total Debt",            ['Total Debt']),
        ("Net Debt",              ['Net Debt']),
        ("Book Value / Share",    ['Book Value', 'Tangible Book Value']),
    ]
    render_fin_table(df, bs_rows)

# ── CASH FLOW ─────────────────────────────────────────────────────────────────
with cashflow_tab:
    st.markdown('<div class="section-title">Cash Flow Statement</div>', unsafe_allow_html=True)
    df = fins.get('cashflow_annual') if annual else fins.get('cashflow_quarterly')
    cf_rows = [
        ("Operating Cash Flow",  ['Operating Cash Flow', 'Cash From Operations', 'Total Cash From Operating Activities']),
        ("Capital Expenditure",  ['Capital Expenditure', 'Capital Expenditures']),
        ("Free Cash Flow",       ['Free Cash Flow']),
        ("Dividends Paid",       ['Common Stock Dividend Paid', 'Payment Of Dividends', 'Dividends Paid']),
        ("Share Buybacks",       ['Repurchase Of Capital Stock', 'Common Stock Repurchase']),
    ]
    # Highlight FCF label
    cf_rows_display = cf_rows
    render_fin_table(df, cf_rows_display)

st.caption("Source: yfinance · 24h cache")
