import streamlit as st
import sys, os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info, get_earnings_data, get_analyst_data

st.set_page_config(page_title="Earnings · Quant Terminal", page_icon="📅", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 📅 Earnings")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
    xaxis=dict(gridcolor='#1A1D2E'),
    yaxis=dict(gridcolor='#1A1D2E'),
)

with st.spinner(f"Loading earnings for {ticker} …"):
    info    = get_ticker_info(ticker)
    earn    = get_earnings_data(ticker)
    analyst = get_analyst_data(ticker)

# ── EARNINGS CALENDAR ─────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Earnings Calendar</div>', unsafe_allow_html=True)

cal_c1, cal_c2 = st.columns(2)

with cal_c1:
    # Next earnings date
    next_date = None
    calendar  = earn.get('calendar')
    if calendar is not None:
        try:
            if isinstance(calendar, dict):
                nd = calendar.get('Earnings Date')
                if nd:
                    next_date = pd.Timestamp(nd[0]) if isinstance(nd, list) else pd.Timestamp(nd)
            elif hasattr(calendar, 'iloc'):
                for col in ['Earnings Date', 'earningsDate']:
                    if col in calendar.columns:
                        vals = calendar[col].dropna()
                        if not vals.empty:
                            next_date = pd.Timestamp(vals.iloc[0])
                            break
        except Exception:
            pass

    if next_date is None:
        ed = earn.get('earnings_dates')
        if ed is not None and not ed.empty:
            try:
                future = ed[ed.index > pd.Timestamp.now(tz='UTC')]
                if not future.empty:
                    next_date = future.index[-1]
            except Exception:
                pass

    if next_date:
        try:
            nd_naive = next_date.tz_localize(None) if next_date.tzinfo else next_date
            days_left = (nd_naive.date() - date.today()).days
            color = '#00FF41' if days_left >= 0 else '#888888'
            st.markdown(f"""
            <div class="stat-card">
              <div class="stat-label">NEXT EARNINGS DATE</div>
              <div class="stat-value" style="color:{color}">{nd_naive.strftime('%B %d, %Y')}</div>
            </div>""", unsafe_allow_html=True)
            if days_left >= 0:
                st.markdown(f"""
                <div class="stat-card">
                  <div class="stat-label">COUNTDOWN</div>
                  <div class="stat-value" style="color:#FFD700">{days_left} days</div>
                </div>""", unsafe_allow_html=True)
        except Exception:
            st.info("Next earnings date: data format issue.")
    else:
        st.info("Next earnings date not available.")

with cal_c2:
    eps_fwd = info.get('forwardEps')
    rev_fwd = info.get('revenueEstimatesAvg')
    st.markdown(f"""
    <div class="stat-card">
      <div class="stat-label">FORWARD EPS ESTIMATE</div>
      <div class="stat-value">${eps_fwd:.2f}</div>
    </div>""" if eps_fwd else "", unsafe_allow_html=True)

st.markdown("---")

# ── EARNINGS HISTORY TABLE ────────────────────────────────────────────────────
st.markdown('<div class="section-title">Earnings History (Last 12 Quarters)</div>', unsafe_allow_html=True)

ed = earn.get('earnings_dates')
if ed is not None and not ed.empty:
    try:
        ed_sorted = ed.sort_index(ascending=False).head(12)
        rows = []
        for dt, row in ed_sorted.iterrows():
            try:
                dt_str   = str(dt)[:10]
                est      = row.get('EPS Estimate') if 'EPS Estimate' in row.index else None
                reported = row.get('Reported EPS') if 'Reported EPS' in row.index else None
                surprise = row.get('Surprise(%)') if 'Surprise(%)' in row.index else None

                if est is None: est = row.iloc[0] if len(row) > 0 else None
                if reported is None: reported = row.iloc[1] if len(row) > 1 else None
                if surprise is None: surprise = row.iloc[2] if len(row) > 2 else None

                beat = None
                if surprise is not None and not pd.isna(surprise):
                    beat = float(surprise) > 0

                rows.append({
                    'Date': dt_str,
                    'EPS Estimate': f"${float(est):.2f}" if est is not None and not pd.isna(est) else 'N/A',
                    'EPS Actual':   f"${float(reported):.2f}" if reported is not None and not pd.isna(reported) else 'N/A',
                    'Surprise %':   f"{float(surprise):+.1f}%" if surprise is not None and not pd.isna(surprise) else 'N/A',
                    '_beat': beat,
                })
            except Exception:
                pass

        if rows:
            html = """
            <div style="overflow-x:auto;">
            <table class="fin-table">
              <thead><tr>
                <th style="text-align:left">Date</th>
                <th>EPS Estimate</th><th>EPS Actual</th><th>Surprise %</th>
              </tr></thead><tbody>"""
            for r in rows:
                color = '#00FF41' if r['_beat'] else ('#FF4444' if r['_beat'] is False else '#FFFFFF')
                html += f"""<tr>
                  <td>{r['Date']}</td>
                  <td>{r['EPS Estimate']}</td>
                  <td style="color:{color}">{r['EPS Actual']}</td>
                  <td style="color:{color}">{r['Surprise %']}</td>
                </tr>"""
            html += "</tbody></table></div>"
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("Could not parse earnings history rows.")
    except Exception as e:
        st.warning(f"Earnings history parsing error: {e}")
else:
    st.info("Earnings history not available.")

st.markdown("---")

# ── EPS SURPRISE CHART ────────────────────────────────────────────────────────
st.markdown('<div class="section-title">EPS Surprise Chart</div>', unsafe_allow_html=True)

if ed is not None and not ed.empty:
    try:
        ed_chart = ed.sort_index().tail(12)
        dates, surprises, colors = [], [], []
        for dt, row in ed_chart.iterrows():
            s_col = 'Surprise(%)' if 'Surprise(%)' in row.index else (row.index[2] if len(row) > 2 else None)
            if s_col:
                sv = row.get(s_col)
                if sv is not None and not pd.isna(sv):
                    dates.append(str(dt)[:10])
                    surprises.append(float(sv))
                    colors.append('#00FF41' if float(sv) >= 0 else '#FF4444')

        if dates:
            fig = go.Figure(go.Bar(x=dates, y=surprises, marker_color=colors,
                                   text=[f"{v:+.1f}%" for v in surprises],
                                   textposition='outside'))
            fig.add_hline(y=0, line_color='#FFFFFF', line_width=1)
            fig.update_layout(**DARK, height=320, yaxis_ticksuffix='%',
                              yaxis_title="Surprise %",
                              margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Surprise data not available.")
    except Exception:
        st.info("Could not render surprise chart.")

st.markdown("---")

# ── ANALYST ESTIMATES ─────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Analyst Estimates</div>', unsafe_allow_html=True)

ee  = analyst.get('earnings_estimate')
re  = analyst.get('revenue_estimate')

est_c1, est_c2 = st.columns(2)

with est_c1:
    st.markdown("**EPS ESTIMATES**")
    if ee is not None and not ee.empty:
        try:
            st.dataframe(
                ee.style.format(precision=2),
                use_container_width=True,
            )
        except Exception:
            st.dataframe(ee, use_container_width=True)
    else:
        # Fallback to info dict
        for label, key in [
            ("Current Qtr EPS Estimate",  'earningsEstimateAvg'),
            ("Current Yr EPS Estimate",   'epsForward'),
            ("No. of Analysts",           'numberOfAnalystOpinions'),
        ]:
            v = info.get(key)
            if v:
                st.markdown(f"""
                <div class="metric-row">
                  <span class="metric-label">{label}</span>
                  <span class="metric-value">{v}</span>
                </div>""", unsafe_allow_html=True)

with est_c2:
    st.markdown("**REVENUE ESTIMATES**")
    if re is not None and not re.empty:
        try:
            st.dataframe(re, use_container_width=True)
        except Exception:
            st.info("Revenue estimates available but could not render.")
    else:
        st.info("Revenue estimates not available.")

st.caption("Source: yfinance · earnings_dates · 1h/24h cache")
