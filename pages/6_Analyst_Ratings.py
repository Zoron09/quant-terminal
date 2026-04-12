import streamlit as st
import sys, os
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info, get_analyst_data
from utils.formatters import fmt_price, safe_get

st.set_page_config(page_title="Analyst Ratings · Quant Terminal", page_icon="🎯", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## 🎯 Analyst Ratings")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
)

with st.spinner(f"Loading analyst data for {ticker} …"):
    info    = get_ticker_info(ticker)
    analyst = get_analyst_data(ticker)

current_price = safe_get(info, 'currentPrice') or safe_get(info, 'regularMarketPrice')

# ── CONSENSUS RATING ──────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Consensus Rating</div>', unsafe_allow_html=True)

rec_key   = safe_get(info, 'recommendationKey', '')
rec_mean  = safe_get(info, 'recommendationMean')
n_analysts = safe_get(info, 'numberOfAnalystOpinions')

RATING_MAP = {
    'strong_buy': ('STRONG BUY', '#00FF41'),
    'buy':        ('BUY',        '#00CC33'),
    'hold':       ('HOLD',       '#FFD700'),
    'underperform': ('UNDERPERFORM', '#FF8800'),
    'sell':       ('SELL',       '#FF4444'),
}
rating_label, rating_color = RATING_MAP.get(rec_key.lower(), (rec_key.upper() or 'N/A', '#FFFFFF'))

cr_col1, cr_col2 = st.columns([1, 1])
with cr_col1:
    st.markdown(f"""
    <div class="rating-display">
      <div class="stat-label">ANALYST CONSENSUS</div>
      <div class="rating-label" style="color:{rating_color}">{rating_label}</div>
      <div class="rating-sub">{n_analysts or '?'} analysts</div>
      <div class="rating-sub" style="margin-top:4px;">
        Mean: {f'{rec_mean:.1f}/5.0' if rec_mean else 'N/A'} (1=Strong Buy, 5=Sell)
      </div>
    </div>""", unsafe_allow_html=True)

# Rating distribution from recommendations summary
rec_summary = analyst.get('recommendations_summary')
with cr_col2:
    if rec_summary is not None and not rec_summary.empty:
        try:
            # Try to build a donut chart from distribution
            period_row = rec_summary.iloc[0]
            buy_cols    = [c for c in rec_summary.columns if 'buy' in c.lower() or 'strongBuy' in c.lower()]
            hold_cols   = [c for c in rec_summary.columns if 'hold' in c.lower()]
            sell_cols   = [c for c in rec_summary.columns if 'sell' in c.lower() or 'underperform' in c.lower()]

            labels, values, colors_pie = [], [], []
            counts = {}
            for col in rec_summary.columns:
                cl = col.lower()
                v  = float(period_row.get(col, 0) or 0)
                if v > 0:
                    if 'strongbuy' in cl or 'strong_buy' in cl:
                        counts['Strong Buy'] = counts.get('Strong Buy', 0) + v
                    elif 'buy' in cl:
                        counts['Buy'] = counts.get('Buy', 0) + v
                    elif 'hold' in cl:
                        counts['Hold'] = counts.get('Hold', 0) + v
                    elif 'sell' in cl or 'underperform' in cl:
                        counts['Sell'] = counts.get('Sell', 0) + v

            color_map = {'Strong Buy': '#00FF41', 'Buy': '#00CC33', 'Hold': '#FFD700', 'Sell': '#FF4444'}
            for k, v in counts.items():
                if v > 0:
                    labels.append(k); values.append(v); colors_pie.append(color_map.get(k, '#888888'))

            if labels:
                fig = go.Figure(go.Pie(labels=labels, values=values,
                                       marker_colors=colors_pie,
                                       hole=0.6, textinfo='label+value'))
                fig.update_layout(**DARK, height=260, showlegend=True,
                                  margin=dict(l=0, r=0, t=20, b=0))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Rating distribution not available.")
        except Exception:
            st.info("Could not parse rating distribution.")
    else:
        st.info("Rating distribution not available.")

st.markdown("---")

# ── PRICE TARGETS ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Price Targets</div>', unsafe_allow_html=True)

pt = analyst.get('analyst_price_targets')
target_low  = safe_get(info, 'targetLowPrice')
target_high = safe_get(info, 'targetHighPrice')
target_mean = safe_get(info, 'targetMeanPrice')
target_med  = safe_get(info, 'targetMedianPrice')

# Try analyst_price_targets df first
if pt is not None and isinstance(pt, pd.DataFrame) and len(pt) > 0:
    try:
        if 'low' in pt.columns:
            target_low  = float(pt['low'].iloc[0])
        if 'high' in pt.columns:
            target_high = float(pt['high'].iloc[0])
        if 'mean' in pt.columns:
            target_mean = float(pt['mean'].iloc[0])
        if 'median' in pt.columns:
            target_med  = float(pt['median'].iloc[0])
    except Exception:
        pass

pt_c1, pt_c2 = st.columns([1, 1])
with pt_c1:
    for label, val, color in [
        ("Low Target",     target_low,  '#FF4444'),
        ("Average Target", target_mean, '#FFD700'),
        ("High Target",    target_high, '#00FF41'),
        ("Current Price",  current_price, '#FFFFFF'),
    ]:
        st.markdown(f"""
        <div class="metric-row">
          <span class="metric-label">{label}</span>
          <span class="metric-value" style="color:{color}">{fmt_price(val)}</span>
        </div>""", unsafe_allow_html=True)

    if current_price and target_mean:
        upside = (target_mean - current_price) / current_price * 100
        upside_color = '#00FF41' if upside >= 0 else '#FF4444'
        st.markdown(f"""
        <div class="metric-row" style="margin-top:8px;">
          <span class="metric-label">Upside to Average Target</span>
          <span class="metric-value" style="color:{upside_color}">{upside:+.1f}%</span>
        </div>""", unsafe_allow_html=True)

with pt_c2:
    if all([target_low, target_high, current_price]):
        try:
            fig_pt = go.Figure()
            fig_pt.add_trace(go.Bar(
                x=[target_high - target_low], y=['Price Range'],
                base=[target_low], orientation='h',
                marker_color='rgba(0,255,65,0.15)',
                marker_line_color='#00FF41',
                marker_line_width=1,
                name='Target Range',
            ))
            fig_pt.add_vline(x=current_price, line_color='#FFFFFF', line_width=2, annotation_text="Current")
            if target_mean:
                fig_pt.add_vline(x=target_mean, line_color='#FFD700', line_width=2,
                                 line_dash='dot', annotation_text="Mean Target")
            fig_pt.update_layout(**DARK, height=180,
                                 margin=dict(l=0, r=0, t=30, b=0),
                                 showlegend=False)
            st.plotly_chart(fig_pt, use_container_width=True)
        except Exception:
            pass

st.markdown("---")

# ── UPGRADES & DOWNGRADES ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">Upgrades &amp; Downgrades</div>', unsafe_allow_html=True)

ud = analyst.get('upgrades_downgrades')
if ud is not None and not ud.empty:
    try:
        ud_display = ud.sort_index(ascending=False).head(20).reset_index()

        # Rename columns for clarity
        col_map = {}
        for c in ud_display.columns:
            cl = c.lower()
            if 'firm' in cl or 'from_grade' not in cl and 'to_grade' not in cl and 'action' not in cl:
                col_map[c] = c

        action_col = next((c for c in ud_display.columns if 'action' in c.lower()), None)
        date_col   = ud_display.columns[0]

        html = """<div style="overflow-x:auto;"><table class="fin-table">
        <thead><tr>"""
        for col in ud_display.columns[:6]:
            html += f'<th style="text-align:left">{col}</th>'
        html += "</tr></thead><tbody>"

        for _, row in ud_display.head(20).iterrows():
            action = str(row.get(action_col, '')).lower() if action_col else ''
            row_color = '#00FF4120' if 'up' in action else ('#FF444420' if 'down' in action else 'transparent')
            html += f'<tr style="background:{row_color};">'
            for col in ud_display.columns[:6]:
                html += f'<td style="text-align:left">{row.get(col, "")}</td>'
            html += "</tr>"
        html += "</tbody></table></div>"
        st.markdown(html, unsafe_allow_html=True)
    except Exception as e:
        st.dataframe(ud.head(20), use_container_width=True)
else:
    st.info("Upgrade/downgrade history not available.")

st.caption("Source: yfinance · 24h cache")
