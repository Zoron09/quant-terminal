"""
Tab 13 — Market Dashboard (Phase 5)
Index cards with sparklines, sector heatmap, market breadth,
VIX fear gauge, currencies & commodities.
"""
import streamlit as st
import sys, os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_price_history

st.set_page_config(page_title="Market Dashboard · Quant Terminal", page_icon="🌐", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

render_sidebar()

DARK   = '#0E1117'
GREEN  = '#00FF41'
RED    = '#FF4444'
YELLOW = '#FFD700'
GRAY   = '#888888'
BLUE   = '#00BFFF'

st.markdown("## 🌐 Market Dashboard")


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _get_quote(sym: str) -> dict:
    """Return {price, prev_close, chg_pct, sparkline} for a symbol."""
    try:
        import yfinance as yf
        t  = yf.Ticker(sym)
        fi = t.fast_info
        p  = fi.get('lastPrice') or fi.get('regularMarketPrice')
        pc = fi.get('previousClose') or fi.get('regularMarketPreviousClose')
        chg_pct = round((p - pc) / pc * 100, 2) if p and pc else 0.0
        return {'price': p, 'prev_close': pc, 'chg_pct': chg_pct}
    except Exception:
        return {'price': None, 'prev_close': None, 'chg_pct': 0.0}


@st.cache_data(ttl=900, show_spinner=False)
def _get_sparkline(sym: str) -> list[float]:
    """30-day close prices for sparkline."""
    try:
        df = get_price_history(sym, period='1mo', interval='1d')
        if df is not None and not df.empty:
            return df['Close'].dropna().tolist()
    except Exception:
        pass
    return []


@st.cache_data(ttl=900, show_spinner=False)
def _breadth_data(symbols: tuple[str, ...]) -> dict:
    """
    Compute % of symbols above 50MA and 200MA.
    Uses 1-year daily bars via yfinance.
    """
    above50 = above200 = total = 0
    for sym in symbols:
        try:
            df = get_price_history(sym, period='1y', interval='1d')
            if df is None or df.empty or len(df) < 50:
                continue
            close = df['Close'].dropna()
            price = float(close.iloc[-1])
            ma50  = float(close.rolling(50, min_periods=25).mean().iloc[-1])
            ma200 = float(close.rolling(200, min_periods=100).mean().iloc[-1]) if len(close) >= 100 else 0
            total += 1
            if price > ma50:
                above50 += 1
            if ma200 > 0 and price > ma200:
                above200 += 1
        except Exception:
            pass
    return {
        'total':    total,
        'above50':  above50,
        'above200': above200,
        'pct50':    round(above50 / total * 100, 1) if total else 0,
        'pct200':   round(above200 / total * 100, 1) if total else 0,
    }


def _sparkline_fig(vals: list[float], color: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        y=vals, mode='lines',
        line=dict(color=color, width=1.5),
        fill='tozeroy',
        fillcolor=f'rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)',
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=50,
        showlegend=False,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def _index_card(col, label: str, sym: str, fmt_price_fn=None):
    q    = _get_quote(sym)
    spark = _get_sparkline(sym)
    p    = q['price']
    pct  = q['chg_pct']
    color = GREEN if pct >= 0 else RED
    p_str = f"{p:,.2f}" if p else "N/A"

    with col:
        st.markdown(f"""
<div style="background:#161B22;border:1px solid #222;border-radius:8px;
            padding:12px 14px;margin-bottom:4px;">
  <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>
  <div style="color:white;font-size:20px;font-weight:bold;font-family:monospace;margin-top:2px;">
    {p_str}
  </div>
  <div style="color:{color};font-size:13px;font-family:monospace;">
    {'+' if pct >= 0 else ''}{pct:.2f}%
  </div>
</div>""", unsafe_allow_html=True)
        if spark:
            st.plotly_chart(_sparkline_fig(spark, color), use_container_width=True, config={'staticPlot': True})


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: INDEX CARDS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📊 Global Indices")

indices = [
    ("S&P 500",   "^GSPC"),
    ("NASDAQ",    "^IXIC"),
    ("Dow Jones", "^DJI"),
    ("Nifty 50",  "^NSEI"),
    ("Sensex",    "^BSESN"),
    ("Russell 2K","^RUT"),
]

idx_cols = st.columns(6)
with st.spinner("Loading index quotes…"):
    for (label, sym), col in zip(indices, idx_cols):
        _index_card(col, label, sym)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: SECTOR HEATMAP
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🔥 Sector Performance Heatmap")

SECTORS = [
    ("Technology",   "XLK"),
    ("Financials",   "XLF"),
    ("Energy",       "XLE"),
    ("Health Care",  "XLV"),
    ("Industrials",  "XLI"),
    ("Cons. Staples","XLP"),
    ("Utilities",    "XLU"),
    ("Cons. Disc.",  "XLY"),
    ("Comm. Svcs",   "XLC"),
    ("Real Estate",  "XLRE"),
    ("Materials",    "XLB"),
]

with st.spinner("Loading sector ETF data…"):
    sector_data = {}
    for name, sym in SECTORS:
        q = _get_quote(sym)
        sector_data[name] = {'sym': sym, 'pct': q.get('chg_pct', 0) or 0, 'price': q.get('price')}

# Color scale: RED → BLACK → GREEN
def _pct_to_color(pct: float) -> str:
    if pct > 0:
        intensity = min(int(pct / 3 * 200), 200)
        return f"rgb(0,{intensity},0)"
    else:
        intensity = min(int(abs(pct) / 3 * 200), 200)
        return f"rgb({intensity},0,0)"

sc_cols = st.columns(len(SECTORS))
for (name, sym), col in zip(SECTORS, sc_cols):
    d     = sector_data[name]
    pct   = d['pct']
    bg    = _pct_to_color(pct)
    color = GREEN if pct >= 0 else RED
    p_str = f"${d['price']:,.2f}" if d['price'] else "N/A"
    col.markdown(f"""
<div style="background:{bg};border:1px solid #333;border-radius:6px;
            padding:10px 6px;text-align:center;margin-bottom:4px;">
  <div style="color:white;font-size:10px;font-family:monospace;font-weight:bold;">{sym}</div>
  <div style="color:white;font-size:9px;color:#DDD;">{name}</div>
  <div style="color:white;font-size:13px;font-weight:bold;margin-top:4px;font-family:monospace;">
    {'+' if pct >= 0 else ''}{pct:.2f}%
  </div>
  <div style="color:#CCC;font-size:10px;font-family:monospace;">{p_str}</div>
</div>""", unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: MARKET BREADTH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📈 Market Breadth")

# Use S&P 500 tickers from JSON if available, else use sector ETFs as proxy
import json as _json
_sp500_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'sp500_tickers.json')
if os.path.exists(_sp500_path):
    with open(_sp500_path) as _f:
        _breadth_universe = _json.load(_f)[:100]  # limit to 100 for speed
else:
    _breadth_universe = [s for _, s in SECTORS]  # fallback to sector ETFs

breadth_col1, breadth_col2, breadth_col3 = st.columns(3)

with breadth_col1:
    if st.button("Compute Market Breadth (S&P 500 subset)", key="btn_breadth"):
        with st.spinner(f"Checking {len(_breadth_universe)} stocks vs MAs…"):
            bd = _breadth_data(tuple(_breadth_universe))
        st.session_state['breadth_data'] = bd

if 'breadth_data' in st.session_state:
    bd = st.session_state['breadth_data']
    pct50  = bd['pct50']
    pct200 = bd['pct200']
    c50_color  = GREEN if pct50  > 60 else YELLOW if pct50  > 40 else RED
    c200_color = GREEN if pct200 > 60 else YELLOW if pct200 > 40 else RED

    b1, b2, b3 = st.columns(3)
    b1.markdown(f"""
<div class="stat-card" style="border-left-color:{c50_color};">
  <div class="stat-label">% Above 50MA</div>
  <div class="stat-value" style="color:{c50_color}">{pct50:.1f}%</div>
  <div style="color:#888;font-size:11px;">{bd['above50']}/{bd['total']} stocks</div>
</div>""", unsafe_allow_html=True)

    b2.markdown(f"""
<div class="stat-card" style="border-left-color:{c200_color};">
  <div class="stat-label">% Above 200MA</div>
  <div class="stat-value" style="color:{c200_color}">{pct200:.1f}%</div>
  <div style="color:#888;font-size:11px;">{bd['above200']}/{bd['total']} stocks</div>
</div>""", unsafe_allow_html=True)

    adv_text = "Bullish" if pct50 > 60 else ("Neutral" if pct50 > 40 else "Bearish")
    adv_col  = GREEN if pct50 > 60 else YELLOW if pct50 > 40 else RED
    b3.markdown(f"""
<div class="stat-card" style="border-left-color:{adv_col};">
  <div class="stat-label">Market Posture</div>
  <div class="stat-value" style="color:{adv_col}">{adv_text}</div>
  <div style="color:#888;font-size:11px;">Based on 50MA breadth</div>
</div>""", unsafe_allow_html=True)
else:
    st.caption("Click 'Compute Market Breadth' to load breadth data (may take ~30s).")

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: VIX FEAR GAUGE
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 😱 Fear & Greed (VIX-based)")

vix_col, vix_chart_col = st.columns([1, 2])

with st.spinner("Loading VIX…"):
    vix_q = _get_quote('^VIX')
    vix   = vix_q.get('price') or 0
    vix_spark = _get_sparkline('^VIX')

vix_level = (
    "EXTREME FEAR"  if vix >= 40 else
    "FEAR"          if vix >= 28 else
    "NEUTRAL"       if vix >= 18 else
    "GREED"         if vix >= 12 else
    "EXTREME GREED"
)
vix_color = (
    RED    if vix >= 40 else
    '#FF8800' if vix >= 28 else
    YELLOW if vix >= 18 else
    '#88FF00' if vix >= 12 else
    GREEN
)

with vix_col:
    st.markdown(f"""
<div style="background:#161B22;border:2px solid {vix_color};border-radius:8px;
            padding:20px 24px;text-align:center;">
  <div style="color:{GRAY};font-size:11px;font-family:monospace;letter-spacing:2px;">VIX</div>
  <div style="color:{vix_color};font-size:48px;font-weight:bold;font-family:monospace;">
    {vix:.2f}
  </div>
  <div style="color:{vix_color};font-size:16px;font-weight:bold;margin-top:4px;">{vix_level}</div>
  <div style="color:{GRAY};font-size:11px;margin-top:8px;font-family:monospace;">
    &lt;12 Extreme Greed · 12-18 Greed · 18-28 Neutral · 28-40 Fear · 40+ Extreme Fear
  </div>
</div>""", unsafe_allow_html=True)

with vix_chart_col:
    if vix_spark:
        fig_vix = go.Figure(go.Scatter(
            y=vix_spark, mode='lines',
            line=dict(color=vix_color, width=2),
            fill='tozeroy',
            fillcolor=f'rgba(255,68,68,0.1)',
        ))
        fig_vix.add_hline(y=28, line_color='#FF8800', line_dash='dash', line_width=1,
                          annotation_text="Fear (28)", annotation_position="right")
        fig_vix.add_hline(y=18, line_color=YELLOW, line_dash='dash', line_width=1,
                          annotation_text="Neutral (18)", annotation_position="right")
        fig_vix.update_layout(
            paper_bgcolor=DARK, plot_bgcolor='#161B22', height=180,
            margin=dict(l=10, r=60, t=20, b=10),
            yaxis=dict(gridcolor='#222', color=GRAY),
            xaxis=dict(color=GRAY, showticklabels=False),
            font=dict(color='white', family='Courier New'),
            showlegend=False,
            title=dict(text='VIX — 30 Day', font_color=GRAY, font_size=12),
        )
        st.plotly_chart(fig_vix, use_container_width=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: CURRENCIES & COMMODITIES
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 💱 Currencies & Commodities")

WATCHLIST = [
    ("USD/INR",     "USDINR=X",  "$"),
    ("Gold",        "GC=F",      "$"),
    ("Crude Oil",   "CL=F",      "$"),
    ("10Y Treasury","^TNX",      ""),
    ("Bitcoin",     "BTC-USD",   "$"),
    ("CAD/USD",     "CADUSD=X",  ""),
]

cc_cols = st.columns(len(WATCHLIST))
with st.spinner("Loading currencies & commodities…"):
    for (label, sym, prefix), col in zip(WATCHLIST, cc_cols):
        q     = _get_quote(sym)
        p     = q['price']
        pct   = q['chg_pct']
        color = GREEN if pct >= 0 else RED
        p_str = f"{prefix}{p:,.4f}" if (p and prefix == '') else (f"{prefix}{p:,.2f}" if p else "N/A")
        if label == "10Y Treasury":
            p_str = f"{p:.3f}%" if p else "N/A"

        col.markdown(f"""
<div style="background:#161B22;border:1px solid #222;border-radius:8px;
            padding:12px 14px;text-align:center;">
  <div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>
  <div style="color:white;font-size:18px;font-weight:bold;font-family:monospace;margin-top:4px;">
    {p_str}
  </div>
  <div style="color:{color};font-size:12px;font-family:monospace;">
    {'+' if pct >= 0 else ''}{pct:.2f}%
  </div>
</div>""", unsafe_allow_html=True)

st.markdown("---")
st.caption(f"Market Dashboard · Data: yfinance · Refreshes every 5 min · Last: {datetime.now().strftime('%H:%M:%S')}")
