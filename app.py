import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info
from utils.formatters import (
    fmt_large_number, fmt_pct, fmt_price, fmt_number,
    fmt_date, fmt_volume, safe_get, color_val, pe_color,
)

st.set_page_config(
    page_title="Quant Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

_css = os.path.join(os.path.dirname(__file__), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()

st.markdown("## 📊 Overview")

if not ticker:
    st.info("Enter a ticker symbol in the sidebar to begin.")
    st.stop()

with st.spinner(f"Fetching {ticker} …"):
    info = get_ticker_info(ticker)

if not info:
    st.error(f"No data found for **{ticker}**. Check the symbol and try again.")
    st.stop()

# ── TOP BAR ──────────────────────────────────────────────────────────────────
current_price = safe_get(info, 'currentPrice') or safe_get(info, 'regularMarketPrice')
prev_close    = safe_get(info, 'previousClose') or safe_get(info, 'regularMarketPreviousClose')
company_name  = safe_get(info, 'longName', ticker)
currency      = safe_get(info, 'currency', 'USD')
market_state  = safe_get(info, 'marketState', 'CLOSED')

price_change = price_change_pct = None
price_color = '#FFFFFF'

if current_price and prev_close:
    price_change = current_price - prev_close
    price_change_pct = price_change / prev_close * 100
    price_color = '#00FF41' if price_change >= 0 else '#FF4444'

sign = '+' if price_change and price_change >= 0 else ''
change_str = (f"{sign}{price_change:.2f} ({sign}{price_change_pct:.2f}%)"
              if price_change is not None else '')

market_color = '#00FF41' if market_state == 'REGULAR' else '#888888'
market_label = 'LIVE' if market_state == 'REGULAR' else 'CLOSED'

st.markdown(f"""
<div class="top-bar">
  <span class="ticker-symbol">{ticker}</span>
  <span class="company-name">{company_name}</span>
  <span class="top-price" style="color:{price_color}">{fmt_price(current_price)}</span>
  <span class="top-change" style="color:{price_color}">{change_str}</span>
  <span class="market-badge"
        style="background:{market_color}18;color:{market_color};border:1px solid {market_color};">
    ● {market_label}
  </span>
  <span style="font-size:11px;color:#555;font-family:monospace;">
    {currency} · yfinance (15-min delay)
  </span>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── SECTION A: Company Snapshot ───────────────────────────────────────────────
st.markdown('<div class="section-title">Company Snapshot</div>', unsafe_allow_html=True)

col_l, col_r = st.columns(2)

def metric_row(label, value, link=None):
    if value is None or value == 'N/A':
        val_html = '<span style="color:#555">N/A</span>'
    elif link:
        val_html = f'<a href="{link}" target="_blank" style="color:#00FF41;text-decoration:none;">{value}</a>'
    else:
        val_html = f'<span style="color:#FFFFFF">{value}</span>'
    st.markdown(f"""
    <div class="metric-row">
      <span class="metric-label">{label}</span>
      <span class="metric-value">{val_html}</span>
    </div>""", unsafe_allow_html=True)

with col_l:
    st.markdown("**BUSINESS INFO**")
    metric_row("Sector",    safe_get(info, 'sector'))
    metric_row("Industry",  safe_get(info, 'industry'))
    metric_row("Country",   safe_get(info, 'country'))
    emp = safe_get(info, 'fullTimeEmployees')
    metric_row("Employees", f"{int(emp):,}" if emp else None)
    web = safe_get(info, 'website')
    if web:
        metric_row("Website", web, link=web)

    officers = safe_get(info, 'companyOfficers', [])
    if officers:
        st.markdown("**KEY EXECUTIVES**")
        for off in officers[:3]:
            title = (off.get('title') or 'Officer')[:35]
            name  = off.get('name', 'N/A')
            metric_row(title, name)

with col_r:
    st.markdown("**MARKET DATA**")
    mc   = safe_get(info, 'marketCap')
    ev   = safe_get(info, 'enterpriseValue')
    so   = safe_get(info, 'sharesOutstanding')
    fs   = safe_get(info, 'floatShares')
    v10  = safe_get(info, 'averageVolume10days')
    v3m  = safe_get(info, 'averageVolume')
    metric_row("Market Cap",           fmt_large_number(mc))
    metric_row("Enterprise Value",     fmt_large_number(ev))
    metric_row("Shares Outstanding",   fmt_large_number(so, symbol=''))
    metric_row("Float Shares",         fmt_large_number(fs, symbol=''))
    metric_row("Avg Volume (10D)",     fmt_volume(v10))
    metric_row("Avg Volume (3M)",      fmt_volume(v3m))

st.markdown("---")

# ── SECTION B: Business Description ──────────────────────────────────────────
with st.expander("BUSINESS DESCRIPTION", expanded=False):
    summary = safe_get(info, 'longBusinessSummary', 'No description available.')
    st.markdown(
        f'<div style="color:#CCCCCC;font-family:sans-serif;line-height:1.7;font-size:14px;">'
        f'{summary}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── SECTION C: Key Statistics ─────────────────────────────────────────────────
st.markdown('<div class="section-title">Key Statistics</div>', unsafe_allow_html=True)

def stat_card(label, value, color='#FFFFFF'):
    return (f'<div class="stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value" style="color:{color}">{value}</div>'
            f'</div>')

# --- Valuation ---
st.markdown("**VALUATION**")
vc = st.columns(4)

trailing_pe = safe_get(info, 'trailingPE')
forward_pe  = safe_get(info, 'forwardPE')
pb          = safe_get(info, 'priceToBook')
ps          = safe_get(info, 'priceToSalesTrailing12Months')
ev_ebitda   = safe_get(info, 'enterpriseToEbitda')
peg         = safe_get(info, 'pegRatio')

vc[0].markdown(stat_card("Trailing P/E",  fmt_number(trailing_pe), pe_color(trailing_pe)), unsafe_allow_html=True)
vc[0].markdown(stat_card("Forward P/E",   fmt_number(forward_pe),  pe_color(forward_pe)),  unsafe_allow_html=True)
vc[1].markdown(stat_card("Price / Book",  fmt_number(pb)),          unsafe_allow_html=True)
vc[1].markdown(stat_card("Price / Sales", fmt_number(ps)),          unsafe_allow_html=True)
vc[2].markdown(stat_card("EV / EBITDA",   fmt_number(ev_ebitda)),   unsafe_allow_html=True)
vc[2].markdown(stat_card("PEG Ratio",     fmt_number(peg)),         unsafe_allow_html=True)

# --- Profitability ---
st.markdown("**PROFITABILITY**")
pc = st.columns(4)

eps_t  = safe_get(info, 'trailingEps')
eps_f  = safe_get(info, 'forwardEps')
pm     = safe_get(info, 'profitMargins')
om     = safe_get(info, 'operatingMargins')
roe    = safe_get(info, 'returnOnEquity')
roa    = safe_get(info, 'returnOnAssets')

pc[0].markdown(stat_card("EPS (Trailing)", fmt_price(eps_t),  '#00FF41' if eps_t and eps_t > 0 else '#FF4444'), unsafe_allow_html=True)
pc[0].markdown(stat_card("EPS (Forward)",  fmt_price(eps_f),  '#00FF41' if eps_f and eps_f > 0 else '#FF4444'), unsafe_allow_html=True)
pc[1].markdown(stat_card("Profit Margin",  fmt_pct(pm),       color_val(pm)), unsafe_allow_html=True)
pc[1].markdown(stat_card("Oper. Margin",   fmt_pct(om),       color_val(om)), unsafe_allow_html=True)
pc[2].markdown(stat_card("Return on Equity", fmt_pct(roe),    color_val(roe)), unsafe_allow_html=True)
pc[2].markdown(stat_card("Return on Assets", fmt_pct(roa),    color_val(roa)), unsafe_allow_html=True)

# --- Trading ---
st.markdown("**TRADING METRICS**")
tc = st.columns(4)

beta     = safe_get(info, 'beta')
hi52     = safe_get(info, 'fiftyTwoWeekHigh')
lo52     = safe_get(info, 'fiftyTwoWeekLow')
ma50     = safe_get(info, 'fiftyDayAverage')
ma200    = safe_get(info, 'twoHundredDayAverage')
shrt_rat = safe_get(info, 'shortRatio')

ma50_col  = '#00FF41' if (current_price and ma50  and current_price > ma50)  else '#FF4444'
ma200_col = '#00FF41' if (current_price and ma200 and current_price > ma200) else '#FF4444'
hi52_col  = '#00FF41' if (current_price and hi52  and current_price >= hi52 * 0.95) else '#FFFFFF'

tc[0].markdown(stat_card("Beta",         fmt_number(beta)),              unsafe_allow_html=True)
tc[0].markdown(stat_card("Short Ratio",  fmt_number(shrt_rat)),          unsafe_allow_html=True)
tc[1].markdown(stat_card("52-Wk High",   fmt_price(hi52),   hi52_col),   unsafe_allow_html=True)
tc[1].markdown(stat_card("52-Wk Low",    fmt_price(lo52)),               unsafe_allow_html=True)
tc[2].markdown(stat_card("50-Day MA",    fmt_price(ma50),   ma50_col),   unsafe_allow_html=True)
tc[2].markdown(stat_card("200-Day MA",   fmt_price(ma200),  ma200_col),  unsafe_allow_html=True)

# --- Dividends ---
st.markdown("**DIVIDENDS**")
dc = st.columns(4)

div_rate  = safe_get(info, 'dividendRate')
div_yield = safe_get(info, 'dividendYield')
ex_div    = safe_get(info, 'exDividendDate')
payout    = safe_get(info, 'payoutRatio')

dc[0].markdown(stat_card("Dividend Rate",  f"${div_rate:.2f}" if div_rate else 'N/A'), unsafe_allow_html=True)
dc[1].markdown(stat_card("Dividend Yield", fmt_pct(div_yield), '#00FF41' if div_yield else '#888888'), unsafe_allow_html=True)
dc[2].markdown(stat_card("Ex-Div Date",    fmt_date(ex_div)),  unsafe_allow_html=True)
dc[3].markdown(stat_card("Payout Ratio",   fmt_pct(payout)),   unsafe_allow_html=True)

st.markdown("---")
st.caption(f"Data: yfinance · 15-min delayed · Last fetch: {ticker}")
