import streamlit as st
import sys, os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info, get_financials, get_price_history
from utils.formatters import fmt_price, fmt_pct, fmt_large_number, safe_get
from utils.dcf_model import calculate_dcf
from utils.piotroski import calculate_piotroski

st.set_page_config(page_title="Valuation · Quant Terminal", page_icon="💰", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 💰 Valuation & Ratios")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
    xaxis=dict(gridcolor='#1A1D2E'),
    yaxis=dict(gridcolor='#1A1D2E'),
)

with st.spinner(f"Loading {ticker} …"):
    info  = get_ticker_info(ticker)
    fins  = get_financials(ticker)
    hist  = get_price_history(ticker, period='5y')

# ── RATIO TREND DASHBOARD ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">Ratio Trends (5-Year)</div>', unsafe_allow_html=True)

if not hist.empty and info:
    # Build quarterly dates from price history
    price_q = hist['Close'].resample('QE').last().dropna().tail(20)
    dates   = [str(d)[:10] for d in price_q.index]

    def _get_fin(df, keys, col=0):
        if df is None or df.empty:
            return None
        for k in keys:
            if k in df.index:
                try:
                    v = df.loc[k].iloc[col]
                    return float(v) if pd.notna(v) else None
                except:
                    pass
        return None

    bs = fins.get('balance_annual')
    cf = fins.get('cashflow_annual')
    ic = fins.get('income_annual')

    # Static ratios from info (point-in-time, shown as sparklines with available data)
    ratio_metrics = {
        'P/E Ratio':    safe_get(info, 'trailingPE'),
        'P/S Ratio':    safe_get(info, 'priceToSalesTrailing12Months'),
        'EV/EBITDA':    safe_get(info, 'enterpriseToEbitda'),
        'P/B Ratio':    safe_get(info, 'priceToBook'),
        'ROE (%)':      (safe_get(info, 'returnOnEquity') or 0) * 100,
    }

    # Calculate ROIC = NOPAT / Invested Capital
    ebit      = _get_fin(ic, ['Ebit', 'Operating Income'])
    tax_rate  = safe_get(info, 'effectiveTaxRate') or 0.21
    nopat     = ebit * (1 - tax_rate) if ebit else None
    total_assets = _get_fin(bs, ['Total Assets'])
    curr_liab    = _get_fin(bs, ['Current Liabilities', 'Total Current Liabilities'])
    inv_capital  = (total_assets - curr_liab) if (total_assets and curr_liab) else None
    roic = (nopat / inv_capital * 100) if (nopat and inv_capital) else None
    ratio_metrics['ROIC (%)'] = roic

    cols = st.columns(3)
    for i, (name, val) in enumerate(ratio_metrics.items()):
        with cols[i % 3]:
            color = '#00FF41' if val and val > 0 else '#FF4444'
            display = f"{val:.2f}" if val is not None else 'N/A'
            if '%' in name and val:
                display = f"{val:.2f}%"
            st.markdown(f"""
            <div class="stat-card" style="border-left-color:#00BFFF;">
              <div class="stat-label">{name}</div>
              <div class="stat-value" style="color:{color}">{display}</div>
            </div>""", unsafe_allow_html=True)
else:
    st.info("Historical data unavailable for ratio trends.")

st.markdown("---")

# ── DCF VALUATION MODEL ────────────────────────────────────────────────────────
st.markdown('<div class="section-title">DCF Valuation Model</div>', unsafe_allow_html=True)

# Get defaults from data
cf_ann = fins.get('cashflow_annual')
def get_row_val(df, keys, col=0):
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            try:
                v = df.loc[k].iloc[col]
                return float(v) if pd.notna(v) else None
            except:
                pass
    return None

fcf_default      = get_row_val(cf_ann, ['Free Cash Flow']) or 1e9
shares_default   = safe_get(info, 'sharesOutstanding') or 1e9
current_price_v  = safe_get(info, 'currentPrice') or safe_get(info, 'regularMarketPrice') or 100.0

dcf_c1, dcf_c2 = st.columns([1, 1])
with dcf_c1:
    st.markdown("**INPUT PARAMETERS**")
    fcf_b     = st.number_input("Current FCF ($B)",       value=round(fcf_default/1e9, 2), step=0.1, format="%.2f")
    growth    = st.slider("Growth Rate (5-yr) %",         0, 50, 15) / 100
    terminal  = st.slider("Terminal Growth Rate %",       0, 10, 3)  / 100
    wacc      = st.slider("Discount Rate / WACC %",       5, 25, 10) / 100
    fcf_input = fcf_b * 1e9

with dcf_c2:
    st.markdown("**DCF OUTPUT**")
    result = calculate_dcf(fcf_input, growth, terminal, wacc, shares_default)
    if result:
        iv = result['intrinsic_value']
        mos = (iv - current_price_v) / iv * 100 if iv else None
        iv_color  = '#00FF41' if iv > current_price_v else '#FF4444'
        mos_color = '#00FF41' if mos and mos > 0 else '#FF4444'

        st.markdown(f"""
        <div class="stat-card" style="margin-bottom:8px;">
          <div class="stat-label">INTRINSIC VALUE / SHARE</div>
          <div class="stat-value" style="color:{iv_color}">${iv:.2f}</div>
        </div>
        <div class="stat-card" style="margin-bottom:8px;">
          <div class="stat-label">CURRENT PRICE</div>
          <div class="stat-value">${current_price_v:.2f}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">MARGIN OF SAFETY</div>
          <div class="stat-value" style="color:{mos_color}">
            {f"{'+' if mos>=0 else ''}{mos:.1f}%" if mos else 'N/A'}
          </div>
        </div>
        """, unsafe_allow_html=True)

        if mos and mos > 0:
            st.success(f"📗 **UNDERVALUED** — {mos:.1f}% below intrinsic value")
        else:
            st.error(f"📕 **OVERVALUED** — {abs(mos) if mos else '?':.1f}% above intrinsic value")

        # Projection table
        st.markdown("**5-Year FCF Projections**")
        proj_df = pd.DataFrame({
            'Year': range(1, 6),
            'Projected FCF': [f"${v/1e9:.2f}B" for v in result['projected_fcf']],
        })
        st.dataframe(proj_df, hide_index=True, use_container_width=True)
    else:
        st.warning("Could not calculate DCF. Check that WACC > Terminal Growth Rate.")

st.markdown("---")

# ── PIOTROSKI F-SCORE ─────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Piotroski F-Score</div>', unsafe_allow_html=True)

scores = calculate_piotroski(info, fins)

if scores:
    total = scores.get('total', 0)
    if total >= 7:
        score_color, verdict = '#00FF41', 'STRONG'
    elif total >= 5:
        score_color, verdict = '#FFD700', 'MODERATE'
    else:
        score_color, verdict = '#FF4444', 'WEAK'

    sc1, sc2 = st.columns([1, 2])
    with sc1:
        st.markdown(f"""
        <div class="rating-display">
          <div class="stat-label">PIOTROSKI F-SCORE</div>
          <div style="font-size:64px;font-weight:bold;color:{score_color};
                      font-family:'Courier New',monospace;">{total}/9</div>
          <div style="color:{score_color};font-family:monospace;font-weight:bold;
                      font-size:14px;margin-top:6px;">{verdict}</div>
        </div>""", unsafe_allow_html=True)

    with sc2:
        criteria_keys = ['F1','F2','F3','F4','F5','F6','F7','F8','F9']
        for k in criteria_keys:
            if k not in scores:
                continue
            c = scores[k]
            icon  = '✔' if c['pass'] else '✘'
            icolor = '#00FF41' if c['pass'] else '#FF4444'
            st.markdown(f"""
            <div class="criteria-row">
              <span style="color:{icolor};font-weight:bold;font-size:16px;
                           min-width:24px;display:inline-block;">{icon}</span>
              <span style="color:#CCCCCC;flex:1;">{k} — {c['name']}</span>
              <span style="color:#888;font-size:12px;">{c['value']}</span>
            </div>""", unsafe_allow_html=True)
else:
    st.info("Piotroski score unavailable — financial data not found.")

st.caption("Source: yfinance · 24h cache")
