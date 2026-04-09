import streamlit as st
import sys, os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_financials

st.set_page_config(page_title="Growth & Margins · Quant Terminal", page_icon="📈", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 📈 Growth & Margins")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
    xaxis=dict(gridcolor='#1A1D2E', showgrid=True),
    yaxis=dict(gridcolor='#1A1D2E', showgrid=True),
)

with st.spinner(f"Loading financials for {ticker} …"):
    fins = get_financials(ticker)

view = st.radio("Period", ["Annual (5Y)", "Quarterly (8Q)"], horizontal=True)
annual = view.startswith("Annual")


def get_row(df, keys):
    if df is None or df.empty:
        return None
    for k in keys:
        if k in df.index:
            s = df.loc[k].dropna()
            return s
    return None


def series_to_sorted(s, n):
    """Return oldest-first series trimmed to n periods."""
    if s is None:
        return [], []
    s = s.sort_index().tail(n)
    labels = [str(i)[:7] for i in s.index]
    return labels, s.values.tolist()


df_inc = fins.get('income_annual') if annual else fins.get('income_quarterly')
n = 5 if annual else 8

rev_s   = get_row(df_inc, ['Total Revenue', 'Revenue'])
ni_s    = get_row(df_inc, ['Net Income', 'Net Income Common Stockholders'])
gp_s    = get_row(df_inc, ['Gross Profit'])
oi_s    = get_row(df_inc, ['Operating Income', 'Ebit'])

# ── REVENUE & EARNINGS CHART ──────────────────────────────────────────────────
st.markdown('<div class="section-title">Revenue &amp; Net Income</div>', unsafe_allow_html=True)

rev_lbl, rev_vals = series_to_sorted(rev_s, n)
_,        ni_vals  = series_to_sorted(ni_s,  n)

# YoY growth rates
def growth_rates(vals):
    rates = [None]
    for i in range(1, len(vals)):
        if vals[i-1] and vals[i-1] != 0:
            rates.append((vals[i] - vals[i-1]) / abs(vals[i-1]) * 100)
        else:
            rates.append(None)
    return rates

rev_growth = growth_rates(rev_vals)
ni_growth  = growth_rates(ni_vals)

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Bar(x=rev_lbl, y=rev_vals, name="Revenue",    marker_color='#00BFFF', opacity=0.85), secondary_y=False)
fig.add_trace(go.Bar(x=rev_lbl, y=ni_vals,  name="Net Income", marker_color='#00FF41', opacity=0.85), secondary_y=False)
fig.add_trace(go.Scatter(x=rev_lbl, y=rev_growth, name="Rev Growth %", mode='lines+markers',
                          line=dict(color='#FFD700', width=2), marker=dict(size=6)), secondary_y=True)
fig.add_trace(go.Scatter(x=rev_lbl, y=ni_growth,  name="NI Growth %",  mode='lines+markers',
                          line=dict(color='#FF6B6B', width=2, dash='dot'), marker=dict(size=6)), secondary_y=True)
fig.update_layout(barmode='group', **DARK, height=380,
                  legend=dict(orientation='h', y=1.08),
                  margin=dict(l=0, r=0, t=30, b=0))
fig.update_yaxes(title_text="Value ($)", secondary_y=False,
                 tickformat=',.2s', gridcolor='#1A1D2E')
fig.update_yaxes(title_text="Growth %", secondary_y=True,
                 ticksuffix='%', gridcolor='#1A1D2E')
st.plotly_chart(fig, use_container_width=True)

# ── MARGIN TRENDS ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Margin Trends</div>', unsafe_allow_html=True)

rev_raw = get_row(df_inc, ['Total Revenue', 'Revenue'])
gp_raw  = get_row(df_inc, ['Gross Profit'])
oi_raw  = get_row(df_inc, ['Operating Income', 'Ebit'])
ni_raw  = get_row(df_inc, ['Net Income', 'Net Income Common Stockholders'])

def margin_series(num_s, den_s, n):
    if num_s is None or den_s is None:
        return [], []
    idx = num_s.index.intersection(den_s.index)
    merged = pd.DataFrame({'num': num_s[idx], 'den': den_s[idx]}).dropna()
    merged = merged.sort_index().tail(n)
    labels = [str(i)[:7] for i in merged.index]
    margins = [(r['num'] / r['den'] * 100) if r['den'] else None for _, r in merged.iterrows()]
    return labels, margins

lbl_gm, gm_vals = margin_series(gp_raw,  rev_raw, n)
lbl_om, om_vals = margin_series(oi_raw,  rev_raw, n)
lbl_nm, nm_vals = margin_series(ni_raw,  rev_raw, n)

common_lbl = lbl_gm or lbl_om or lbl_nm

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=common_lbl, y=gm_vals, name="Gross Margin",     mode='lines+markers',
                           line=dict(color='#00FF41', width=2),  marker=dict(size=7)))
fig2.add_trace(go.Scatter(x=common_lbl, y=om_vals, name="Operating Margin", mode='lines+markers',
                           line=dict(color='#00BFFF', width=2),  marker=dict(size=7)))
fig2.add_trace(go.Scatter(x=common_lbl, y=nm_vals, name="Net Margin",       mode='lines+markers',
                           line=dict(color='#FFD700', width=2),  marker=dict(size=7)))
fig2.add_hline(y=0, line_color='#FF4444', line_dash='dot', line_width=1)
fig2.update_layout(**DARK, height=340, yaxis_ticksuffix='%',
                   legend=dict(orientation='h', y=1.08),
                   margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(fig2, use_container_width=True)

# ── EPS GROWTH CHART ──────────────────────────────────────────────────────────
st.markdown('<div class="section-title">EPS Growth (Quarterly — Earnings Acceleration)</div>', unsafe_allow_html=True)

df_q    = fins.get('income_quarterly')
eps_s   = get_row(df_q, ['Diluted EPS', 'Diluted Eps', 'Basic EPS', 'Basic Eps'])

if eps_s is not None and not eps_s.empty:
    eps_sorted = eps_s.sort_index().tail(12)
    q_labels   = [str(i)[:10] for i in eps_sorted.index]
    eps_vals   = eps_sorted.values.tolist()

    # YoY EPS growth (vs same quarter prior year)
    bar_colors  = []
    growth_text = []
    for i, v in enumerate(eps_vals):
        if i >= 4 and eps_vals[i-4] and eps_vals[i-4] != 0:
            g = (v - eps_vals[i-4]) / abs(eps_vals[i-4]) * 100
            bar_colors.append('#00FF41' if g >= 0 else '#FF4444')
            growth_text.append(f"{'+' if g>=0 else ''}{g:.1f}%")
        else:
            bar_colors.append('#888888')
            growth_text.append('')

    fig3 = go.Figure(go.Bar(
        x=q_labels, y=eps_vals,
        marker_color=bar_colors,
        text=growth_text, textposition='outside',
        textfont=dict(size=10, color='#CCCCCC'),
    ))
    fig3.update_layout(**DARK, height=340,
                       yaxis_title="EPS ($)",
                       margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig3, use_container_width=True)
    st.caption("Bar color = YoY growth vs same quarter prior year. Green = acceleration, Red = deceleration.")
else:
    st.info("EPS data not available for this ticker.")

st.caption("Source: yfinance · 24h cache")
