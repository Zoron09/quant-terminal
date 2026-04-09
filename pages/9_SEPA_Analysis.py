import streamlit as st
import sys, os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_price_history, get_financials, get_benchmark
from utils.sepa_engine import (
    compute_trend_template, compute_stage, compute_rs,
    detect_vcp, compute_earnings_acceleration, compute_sepa_score,
    _sma,
)
from utils.formatters import fmt_number, fmt_pct, safe_get

st.set_page_config(page_title="SEPA Analysis · Quant Terminal", page_icon="🎯", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

DARK = '#0E1117'
GREEN = '#00FF41'
RED = '#FF4444'
YELLOW = '#FFD700'
GRAY = '#888888'

ticker = render_sidebar()
st.markdown("## 🎯 SEPA / Minervini Analysis")

if not ticker:
    st.info("Enter a ticker symbol in the sidebar to begin.")
    st.stop()

# ── load data ─────────────────────────────────────────────────────────────────
with st.spinner(f"Computing SEPA metrics for {ticker} …"):
    df = get_price_history(ticker, period='3y', interval='1d')
    benchmark_ticker = get_benchmark(ticker)
    bench_df = get_price_history(benchmark_ticker, period='3y', interval='1d')
    fin_data = get_financials(ticker)

if df is None or df.empty:
    st.error(f"No price history found for **{ticker}**.")
    st.stop()

# ── compute all metrics ───────────────────────────────────────────────────────
trend   = compute_trend_template(df)
stage   = compute_stage(df)
rs      = compute_rs(df, bench_df)
vcp     = detect_vcp(df, lookback=90)

# Extract quarterly EPS for earnings acceleration
eps_list = []
q_income = fin_data.get('income_quarterly')
if q_income is not None and not q_income.empty:
    eps_row = None
    for key in ['Basic EPS', 'Diluted EPS', 'EPS', 'basicEps', 'dilutedEps']:
        if key in q_income.index:
            eps_row = q_income.loc[key]
            break
    if eps_row is not None:
        eps_list = list(reversed([
            float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None
            for v in eps_row.values
        ]))

earnings_accel = compute_earnings_acceleration(eps_list)

composite = compute_sepa_score(trend, stage, rs, vcp, earnings_accel, df)

# ── COMPOSITE SCORE BAR ───────────────────────────────────────────────────────
score = composite['total']
grade = composite['grade']
grade_color = composite['grade_color']

st.markdown(f"""
<div style="background:#161B22;border:1px solid {grade_color};border-radius:8px;
            padding:20px 24px;margin-bottom:20px;display:flex;align-items:center;
            justify-content:space-between;">
  <div>
    <div style="color:{GRAY};font-size:11px;font-family:monospace;letter-spacing:2px;">
      SEPA COMPOSITE SCORE
    </div>
    <div style="color:{grade_color};font-size:52px;font-weight:bold;
                font-family:'Courier New',monospace;line-height:1.1;">
      {score:.0f}<span style="font-size:24px;color:{GRAY}">/100</span>
    </div>
    <div style="color:{grade_color};font-size:16px;font-weight:bold;margin-top:4px;">
      Grade {grade}
    </div>
  </div>
  <div style="text-align:right;">
    {'<div style="color:' + GREEN + ';font-size:20px;font-weight:bold;">✓ SEPA QUALIFIED</div>'
      if trend.get('qualified') else
      '<div style="color:' + RED + ';font-size:18px;">✗ NOT QUALIFIED</div>'}
    <div style="color:{GRAY};font-size:13px;margin-top:6px;">
      Trend Template: {trend.get('pass_count', 0)}/8 ·
      Stage: {stage.get('label', 'N/A')} ·
      RS(12M): {rs.get('rs_pct_12m') or 'N/A'}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# Score breakdown bar
bd = composite['breakdown']
fig_score = go.Figure()
cats = ['Trend Template', 'RS Rank', 'Earnings Accel', 'VCP', 'Volume/Stage']
vals = [bd['trend'], bd['rs'], bd['earnings'], bd['vcp'], bd['volume_stage']]
maxes = [30, 20, 20, 15, 15]
colors_bar = [GREEN if v >= m * 0.7 else YELLOW if v >= m * 0.4 else RED
              for v, m in zip(vals, maxes)]

fig_score.add_trace(go.Bar(
    x=cats, y=vals, marker_color=colors_bar, text=[f"{v:.1f}" for v in vals],
    textposition='outside', textfont_color='white',
))
fig_score.update_layout(
    paper_bgcolor=DARK, plot_bgcolor='#161B22',
    height=220, margin=dict(t=20, b=20, l=10, r=10),
    yaxis=dict(range=[0, 35], gridcolor='#222', color=GRAY),
    xaxis=dict(color=GRAY),
    font=dict(color='white', family='Courier New'),
    showlegend=False,
)
st.plotly_chart(fig_score, use_container_width=True)
st.markdown("---")

# ── SECTION 1: TREND TEMPLATE ─────────────────────────────────────────────────
st.markdown("### 📐 Minervini Trend Template")

if trend.get('error'):
    st.warning(trend['error'])
else:
    cols_tt = st.columns([1, 1, 1, 1])
    for i, c in enumerate(trend.get('criteria', [])):
        col = cols_tt[i % 4]
        icon = "✅" if c['result'] else "❌"
        prox = c.get('proximity', None)

        # Color logic: red = failing, yellow = passing but within 10% of failing, green = passing
        if not c['result']:
            bg, border, prox_color = "#2a0d0d", RED, RED
            prox_str = f"▼ {abs(prox):.1f}% below threshold" if prox is not None else ""
        elif prox is not None and 0 < prox < 10:
            bg, border, prox_color = "#1a1500", YELLOW, YELLOW
            prox_str = f"⚠ {prox:.1f}% above threshold (near fail)"
        else:
            bg, border, prox_color = "#0d2818", GREEN, GRAY
            prox_str = f"{prox:.1f}% above threshold" if prox is not None else ""

        col.markdown(f"""
<div style="background:{bg};border:1px solid {border};border-radius:6px;
            padding:10px 12px;margin-bottom:8px;">
  <div style="font-size:13px;font-weight:bold;color:#FFFFFF;">
    {icon} #{c['id']} {c['label']}
  </div>
  <div style="font-size:11px;color:{GRAY};font-family:monospace;margin-top:4px;">
    {c['value']}
  </div>
  <div style="font-size:10px;color:{prox_color};font-family:monospace;margin-top:3px;">
    {prox_str}
  </div>
</div>""", unsafe_allow_html=True)

    pass_color = GREEN if trend['qualified'] else (YELLOW if trend['pass_count'] >= 5 else RED)
    st.markdown(f"""
<div style="background:#161B22;border:1px solid {pass_color};border-radius:6px;
            padding:12px 16px;text-align:center;margin:10px 0;">
  <span style="color:{pass_color};font-size:18px;font-weight:bold;font-family:monospace;">
    PASSED {trend['pass_count']}/8 CRITERIA &nbsp;·&nbsp;
    {'SEPA QUALIFIED ✓' if trend['qualified'] else 'NOT QUALIFIED ✗'}
  </span>
</div>""", unsafe_allow_html=True)

st.markdown("---")

# ── SECTION 2: PRICE CHART + MAs ─────────────────────────────────────────────
st.markdown("### 📈 Price Chart with Moving Averages")

plot_df = df.tail(504).copy()  # 2 years of daily data
close = plot_df['Close']

fig_price = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.75, 0.25], vertical_spacing=0.04)

# Candlestick
fig_price.add_trace(go.Candlestick(
    x=plot_df.index, open=plot_df['Open'], high=plot_df['High'],
    low=plot_df['Low'], close=close,
    name='Price', increasing_fillcolor='#0d2818', increasing_line_color=GREEN,
    decreasing_fillcolor='#2a0d0d', decreasing_line_color=RED,
), row=1, col=1)

# MAs
for n, color, dash in [(50, '#00BFFF', 'solid'), (150, '#FFD700', 'dash'), (200, '#FF69B4', 'dot')]:
    ma = _sma(close, n)
    fig_price.add_trace(go.Scatter(
        x=plot_df.index, y=ma, name=f'MA{n}',
        line=dict(color=color, width=1.5, dash=dash), opacity=0.9,
    ), row=1, col=1)

# Volume
vol_colors = [GREEN if c >= o else RED
              for c, o in zip(plot_df['Close'], plot_df['Open'])]
fig_price.add_trace(go.Bar(
    x=plot_df.index, y=plot_df['Volume'],
    marker_color=vol_colors, opacity=0.6, name='Volume',
), row=2, col=1)

# Avg volume line
avg_vol = plot_df['Volume'].rolling(50).mean()
fig_price.add_trace(go.Scatter(
    x=plot_df.index, y=avg_vol, name='Avg Vol(50)',
    line=dict(color=YELLOW, width=1, dash='dash'),
), row=2, col=1)

fig_price.update_layout(
    paper_bgcolor=DARK, plot_bgcolor='#161B22',
    height=600, margin=dict(t=10, b=10, l=10, r=10),
    legend=dict(orientation='h', y=1.02, font=dict(size=11, color='white')),
    xaxis_rangeslider_visible=False,
    font=dict(color='white', family='Courier New'),
    yaxis=dict(gridcolor='#222', color=GRAY),
    yaxis2=dict(gridcolor='#222', color=GRAY),
    xaxis2=dict(color=GRAY),
)
st.plotly_chart(fig_price, use_container_width=True)

st.markdown("---")

# ── SECTION 3: STAGE + RS ─────────────────────────────────────────────────────
col_stage, col_rs = st.columns(2)

with col_stage:
    st.markdown("### 🏗️ Weinstein Stage Analysis")
    s_color = stage.get('color', GRAY)
    s_label = stage.get('label', 'N/A')
    s_num   = stage.get('stage', 0)

    stage_descs = {
        1: "Sideways consolidation. Volume drying up. Potential basing.",
        2: "Uptrend with rising 150-day MA. Ideal for entries.",
        3: "Uptrend losing steam. Distribution likely. Caution.",
        4: "Downtrend with falling 150-day MA. Avoid or short.",
    }
    st.markdown(f"""
<div style="background:#161B22;border:2px solid {s_color};border-radius:8px;padding:20px 24px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">WEINSTEIN STAGE</div>
  <div style="color:{s_color};font-size:32px;font-weight:bold;font-family:monospace;">{s_label}</div>
  <div style="color:#CCCCCC;font-size:13px;margin-top:8px;">{stage_descs.get(s_num, '')}</div>
  <div style="color:{GRAY};font-size:11px;font-family:monospace;margin-top:12px;">
    Price vs MA150: {'Above ↑' if stage.get('price_above_ma') else 'Below ↓'} &nbsp;·&nbsp;
    MA150 Slope: {'Rising ↑' if stage.get('ma_slope_up') else 'Falling ↓'}
  </div>
</div>""", unsafe_allow_html=True)

with col_rs:
    st.markdown("### ⚡ Relative Strength")
    rs12 = rs.get('rs_pct_12m')
    rs6  = rs.get('rs_pct_6m')
    rs12_color = GREEN if rs12 and rs12 >= 70 else YELLOW if rs12 and rs12 >= 50 else RED
    rs6_color  = GREEN if rs6  and rs6  >= 70 else YELLOW if rs6  and rs6  >= 50 else RED

    st.markdown(f"""
<div style="background:#161B22;border:1px solid #333;border-radius:8px;padding:20px 24px;">
  <div style="display:flex;justify-content:space-around;margin-bottom:16px;">
    <div style="text-align:center;">
      <div style="color:{GRAY};font-size:11px;font-family:monospace;">RS RANK (12M)</div>
      <div style="color:{rs12_color};font-size:40px;font-weight:bold;font-family:monospace;">
        {rs12 if rs12 else 'N/A'}
      </div>
      <div style="color:{GRAY};font-size:11px;">{'✓ SEPA OK' if rs12 and rs12 >= 70 else '✗ Below 70'}</div>
    </div>
    <div style="text-align:center;">
      <div style="color:{GRAY};font-size:11px;font-family:monospace;">RS RANK (6M)</div>
      <div style="color:{rs6_color};font-size:40px;font-weight:bold;font-family:monospace;">
        {rs6 if rs6 else 'N/A'}
      </div>
    </div>
  </div>
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">
    Benchmark: {benchmark_ticker} &nbsp;·&nbsp; SEPA minimum: 70+
  </div>
</div>""", unsafe_allow_html=True)

# RS Line Chart
if rs.get('rs_line') is not None and len(rs['rs_line']) > 10:
    rs_series = rs['rs_line'].tail(504)
    fig_rs = go.Figure()
    fig_rs.add_trace(go.Scatter(
        x=rs_series.index, y=rs_series.values,
        line=dict(color=GREEN, width=1.5), fill='tozeroy',
        fillcolor='rgba(0,255,65,0.06)', name='RS Line',
    ))
    fig_rs.update_layout(
        paper_bgcolor=DARK, plot_bgcolor='#161B22', height=200,
        margin=dict(t=10, b=10, l=10, r=10),
        yaxis=dict(gridcolor='#222', color=GRAY, showticklabels=False),
        xaxis=dict(color=GRAY),
        font=dict(color='white', family='Courier New'),
        showlegend=False, title=dict(text='RS Line (Stock / Benchmark)', font_color=GRAY, font_size=12),
    )
    st.plotly_chart(fig_rs, use_container_width=True)

st.markdown("---")

# ── SECTION 4: VCP DETECTION ─────────────────────────────────────────────────
st.markdown("### 🌀 VCP Detection (Volatility Contraction Pattern)")

col_vcp1, col_vcp2 = st.columns([1, 2])

with col_vcp1:
    if vcp.get('vcp_detected'):
        vcp_color = GREEN
        vcp_label = "VCP DETECTED ✓"
    elif vcp.get('invalid_vcp'):
        vcp_color = RED
        vcp_label = "Invalid VCP ✗"
    else:
        vcp_color = YELLOW
        vcp_label = "No VCP Pattern"
    depths = vcp.get('depths', [])

    st.markdown(f"""
<div style="background:#161B22;border:2px solid {vcp_color};border-radius:8px;padding:20px 24px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">PATTERN STATUS</div>
  <div style="color:{vcp_color};font-size:22px;font-weight:bold;font-family:monospace;margin:8px 0;">
    {vcp_label}
  </div>
  <div style="color:#CCCCCC;font-size:13px;">
    Contractions detected: <b style="color:white">{vcp.get('contractions', 0)}</b><br>
    Latest contraction depth: <b style="color:white">{vcp.get('latest_depth', 0):.1f}%</b>
  </div>
  {'<div style="color:' + RED + ';font-size:11px;margin-top:6px;font-family:monospace;">⚠ Non-progressive contraction detected</div>' if vcp.get('invalid_vcp') else ''}
</div>""", unsafe_allow_html=True)

with col_vcp2:
    if depths:
        fig_vcp = go.Figure()
        bar_colors = []
        for i, d in enumerate(depths):
            if i == 0:
                bar_colors.append(GRAY)
            else:
                bar_colors.append(GREEN if d < depths[i-1] else RED)
        fig_vcp.add_trace(go.Bar(
            x=[f"C{i+1}" for i in range(len(depths))],
            y=depths,
            marker_color=bar_colors,
            text=[f"{d:.1f}%" for d in depths],
            textposition='outside', textfont_color='white',
        ))
        fig_vcp.update_layout(
            paper_bgcolor=DARK, plot_bgcolor='#161B22', height=200,
            margin=dict(t=20, b=10, l=10, r=10),
            yaxis=dict(gridcolor='#222', color=GRAY, title='Contraction %'),
            xaxis=dict(color=GRAY, title='Contraction Period'),
            font=dict(color='white', family='Courier New'),
            title=dict(text='Price Contraction Depths (each should be smaller)', font_color=GRAY, font_size=12),
        )
        st.plotly_chart(fig_vcp, use_container_width=True)
    else:
        st.info("Not enough data to plot contraction pattern.")

st.markdown("---")

# ── SECTION 5: EARNINGS ACCELERATION ─────────────────────────────────────────
st.markdown("### 📊 Earnings Acceleration")

accel = earnings_accel.get('accelerating', False)
latest_g = earnings_accel.get('latest_growth')
growth_rates = earnings_accel.get('growth_rates', [])

accel_color = GREEN if accel else YELLOW

col_ea1, col_ea2 = st.columns([1, 2])

with col_ea1:
    st.markdown(f"""
<div style="background:#161B22;border:2px solid {accel_color};border-radius:8px;padding:20px 24px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">ACCELERATION STATUS</div>
  <div style="color:{accel_color};font-size:22px;font-weight:bold;font-family:monospace;margin:8px 0;">
    {'ACCELERATING ✓' if accel else 'Not Accelerating'}
  </div>
  <div style="color:#CCCCCC;font-size:13px;">
    Latest YoY EPS growth:<br>
    <b style="color:white;font-size:18px;">
      {f'{latest_g:+.1f}%' if latest_g is not None else 'N/A'}
    </b>
  </div>
</div>""", unsafe_allow_html=True)

with col_ea2:
    valid_rates = [r for r in growth_rates if r is not None]
    if valid_rates:
        bar_colors_ea = [GREEN if r > 0 else RED for r in valid_rates]
        fig_ea = go.Figure()
        fig_ea.add_trace(go.Bar(
            x=[f"Q{i+1}" for i in range(len(valid_rates))],
            y=valid_rates,
            marker_color=bar_colors_ea,
            text=[f"{r:+.1f}%" for r in valid_rates],
            textposition='outside', textfont_color='white',
        ))
        fig_ea.add_hline(y=0, line_color=GRAY, line_width=1)
        fig_ea.update_layout(
            paper_bgcolor=DARK, plot_bgcolor='#161B22', height=220,
            margin=dict(t=20, b=10, l=10, r=10),
            yaxis=dict(gridcolor='#222', color=GRAY, title='YoY EPS Growth %'),
            xaxis=dict(color=GRAY),
            font=dict(color='white', family='Courier New'),
            title=dict(text='Quarterly EPS YoY Growth Rate', font_color=GRAY, font_size=12),
        )
        st.plotly_chart(fig_ea, use_container_width=True)
    else:
        st.info("Insufficient quarterly EPS data for acceleration analysis.")

st.markdown("---")

# ── SECTION 6: VOLUME DRY-UP + BUY TRIGGER ───────────────────────────────────
st.markdown("### 🔔 Volume Dry-Up & Buy Trigger")

col_vol, col_trig, col_c33 = st.columns(3)

# Volume dry-up at tightest VCP section
with col_vol:
    depths = vcp.get('depths', [])
    vol_dry = None
    vol_dry_confirmed = False
    if depths and len(df) >= 50:
        # Tightest section = last window of VCP lookback
        vol_series = df['Volume'].dropna()
        avg_vol_50 = float(vol_series.rolling(50).mean().iloc[-1]) if len(vol_series) >= 50 else None
        last_10_vol = float(vol_series.tail(10).mean()) if len(vol_series) >= 10 else None
        if avg_vol_50 and last_10_vol:
            vol_dry = last_10_vol / avg_vol_50
            vol_dry_confirmed = vol_dry < 1.0  # below 50d avg = drying up

    if vol_dry is not None:
        vd_color = GREEN if vol_dry_confirmed else YELLOW
        vd_label = "VOLUME DRY-UP ✓" if vol_dry_confirmed else "Volume Not Drying Up"
        vd_ratio = f"{vol_dry:.2f}x 50d avg"
    else:
        vd_color, vd_label, vd_ratio = GRAY, "Insufficient Data", "N/A"

    st.markdown(f"""
<div style="background:#161B22;border:2px solid {vd_color};border-radius:8px;padding:16px 20px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">VOLUME DRY-UP (VCP)</div>
  <div style="color:{vd_color};font-size:18px;font-weight:bold;font-family:monospace;margin:8px 0;">
    {vd_label}
  </div>
  <div style="color:#CCCCCC;font-size:12px;">Recent 10d avg vol: <b>{vd_ratio}</b></div>
  <div style="color:{GRAY};font-size:11px;margin-top:4px;">
    {'Below 50d avg confirms tightening' if vol_dry_confirmed else 'Should be below 50d avg at tightest point'}
  </div>
</div>""", unsafe_allow_html=True)

# Buy trigger zone
with col_trig:
    buy_trigger = False
    pivot_note = "N/A"
    if not trend.get('error') and len(df) >= 50:
        price_now = trend.get('price', 0)
        hi52 = trend.get('hi52', 0)
        vol_series2 = df['Volume'].dropna()
        avg_vol_50_2 = float(vol_series2.rolling(50).mean().iloc[-1]) if len(vol_series2) >= 50 else None
        last_5_vol = float(vol_series2.tail(5).mean()) if len(vol_series2) >= 5 else None
        # Pivot = 52W high used as proxy for most recent consolidation top
        pct_from_hi = (price_now / hi52 - 1) * 100 if hi52 else -999
        vol_expanding = (last_5_vol > avg_vol_50_2 * 1.1) if (last_5_vol and avg_vol_50_2) else False
        within_pivot = pct_from_hi >= -2.0  # within 2% of 52W high = pivot zone
        buy_trigger = within_pivot and vol_expanding
        pivot_note = f"{pct_from_hi:+.1f}% from 52W high | Vol: {(last_5_vol/avg_vol_50_2):.2f}x avg" if (last_5_vol and avg_vol_50_2 and hi52) else "N/A"

    bt_color = GREEN if buy_trigger else GRAY
    bt_label = "BUY TRIGGER ACTIVE 🚀" if buy_trigger else "No Buy Trigger"
    st.markdown(f"""
<div style="background:#161B22;border:2px solid {bt_color};border-radius:8px;padding:16px 20px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">BUY TRIGGER ZONE</div>
  <div style="color:{bt_color};font-size:18px;font-weight:bold;font-family:monospace;margin:8px 0;">
    {bt_label}
  </div>
  <div style="color:#CCCCCC;font-size:12px;">{pivot_note}</div>
  <div style="color:{GRAY};font-size:11px;margin-top:4px;">
    Requires: within 2% of pivot + volume expanding
  </div>
</div>""", unsafe_allow_html=True)

# Code 33 detector
with col_c33:
    code33 = False
    c33_note = "Need quarterly data"
    q_income_c33 = fin_data.get('income_quarterly')
    if q_income_c33 is not None and not q_income_c33.empty:
        try:
            # Get EPS growth (already computed)
            eps_growth_rates = earnings_accel.get('growth_rates', [])

            # Revenue growth quarterly
            rev_row = None
            for rk in ['Total Revenue', 'Revenue', 'totalRevenue']:
                if rk in q_income_c33.index:
                    rev_row = q_income_c33.loc[rk]
                    break

            # Profit margin quarterly
            ni_row, rev_for_margin = None, None
            for nk in ['Net Income', 'Net Income Common Stockholders', 'netIncome']:
                if nk in q_income_c33.index:
                    ni_row = q_income_c33.loc[nk]
                    break
            if rev_row is not None:
                rev_for_margin = rev_row

            rev_growth_q, margin_q = [], []
            if rev_row is not None:
                rev_vals = list(reversed([float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None for v in rev_row.values]))
                for i in range(4, len(rev_vals)):
                    curr = rev_vals[i]; prev = rev_vals[i-4]
                    if curr is not None and prev and prev != 0:
                        rev_growth_q.append((curr - prev) / abs(prev) * 100)
                    else:
                        rev_growth_q.append(None)

            if ni_row is not None and rev_for_margin is not None:
                ni_vals = list(reversed([float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None for v in ni_row.values]))
                rv_vals = list(reversed([float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else None for v in rev_for_margin.values]))
                for i in range(len(ni_vals)):
                    if ni_vals[i] is not None and rv_vals[i] and rv_vals[i] != 0:
                        margin_q.append(ni_vals[i] / rv_vals[i] * 100)
                    else:
                        margin_q.append(None)

            # Code 33: last 3 quarters all three metrics accelerating
            def _accel_last3(rates):
                valid = [r for r in rates if r is not None]
                if len(valid) < 3:
                    return False
                return valid[-1] > valid[-2] > valid[-3]

            # Align lengths
            min_len = min(len(eps_growth_rates), len(rev_growth_q), len(margin_q))
            if min_len >= 3:
                eps_aligned = eps_growth_rates[-min_len:]
                rev_aligned = rev_growth_q[-min_len:]
                mgn_aligned = margin_q[-min_len:]

                # Check last 3 quarters
                def _last3_accel(lst):
                    v = [x for x in lst[-3:] if x is not None]
                    return len(v) >= 3 and v[-1] > v[-2] > v[-3]

                code33 = _last3_accel(eps_aligned) and _last3_accel(rev_aligned) and _last3_accel(mgn_aligned)
                c33_note = "EPS + Revenue + Margin all accelerating 3Q" if code33 else "Not all 3 metrics accelerating"
        except Exception as e:
            c33_note = "Calculation error"

    c33_color = GREEN if code33 else GRAY
    c33_label = "CODE 33 ACTIVE" if code33 else "No Code 33"
    st.markdown(f"""
<div style="background:#161B22;border:2px solid {c33_color};border-radius:8px;padding:16px 20px;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;">CODE 33 DETECTOR</div>
  <div style="color:{c33_color};font-size:18px;font-weight:bold;font-family:monospace;margin:8px 0;">
    {c33_label}
  </div>
  <div style="color:#CCCCCC;font-size:12px;">{c33_note}</div>
  <div style="color:{GRAY};font-size:11px;margin-top:4px;">
    3 consecutive quarters: EPS + Revenue + Margin ALL accelerating
  </div>
</div>""", unsafe_allow_html=True)

st.markdown("---")
st.caption(f"SEPA Engine · Price data: yfinance (3yr daily) · Last updated: {ticker}")
