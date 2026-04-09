import streamlit as st
import sys, os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_ticker_info
from utils.formatters import fmt_price, fmt_large_number, fmt_pct, fmt_number, safe_get

st.set_page_config(page_title="Peer Comparison · Quant Terminal", page_icon="⚡", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

ticker = render_sidebar()
st.markdown("## ⚡ Peer Comparison")

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

# ── SECTOR PEER MAP ───────────────────────────────────────────────────────────
SECTOR_PEERS = {
    'Technology': ['AAPL','MSFT','GOOGL','META','NVDA','AMZN','CRM','ADBE','ORCL','INTC','AMD','QCOM'],
    'Communication Services': ['GOOGL','META','NFLX','DIS','T','VZ','TMUS','ATVI','EA','TTWO'],
    'Consumer Cyclical': ['AMZN','TSLA','HD','NKE','SBUX','MCD','BKNG','TGT','LOW','F','GM'],
    'Consumer Defensive': ['WMT','COST','PG','KO','PEP','PM','MO','CL','GIS','K'],
    'Healthcare': ['JNJ','UNH','PFE','ABBV','MRK','TMO','ABT','DHR','BMY','AMGN','GILD','CVS'],
    'Financial Services': ['BRK-B','JPM','BAC','WFC','GS','MS','C','AXP','BLK','SCHW','V','MA'],
    'Industrials': ['GE','HON','UPS','CAT','DE','MMM','BA','LMT','RTX','NOC','FDX'],
    'Energy': ['XOM','CVX','COP','SLB','EOG','MPC','PSX','VLO','OXY','HAL'],
    'Basic Materials': ['LIN','APD','ECL','DD','NEM','FCX','NUE','VMC','MLM','CF'],
    'Real Estate': ['AMT','PLD','CCI','EQIX','SPG','O','DLR','WELL','PSA','AVB'],
    'Utilities': ['NEE','DUK','SO','D','AEP','EXC','SRE','XEL','ED','WEC'],
}

METRIC_COLS = [
    ('Ticker',        None),
    ('Price',         'currentPrice'),
    ('Mkt Cap',       'marketCap'),
    ('P/E',           'trailingPE'),
    ('P/S',           'priceToSalesTrailing12Months'),
    ('EPS Growth',    'earningsGrowth'),
    ('Rev Growth',    'revenueGrowth'),
    ('Profit Margin', 'profitMargins'),
    ('ROE',           'returnOnEquity'),
    ('Beta',          'beta'),
]

with st.spinner(f"Loading {ticker} info …"):
    base_info = get_ticker_info(ticker)

if not base_info:
    st.error(f"No data found for **{ticker}**.")
    st.stop()

sector   = safe_get(base_info, 'sector', '')
industry = safe_get(base_info, 'industry', '')

st.markdown(f"**Sector:** {sector}  |  **Industry:** {industry}")

# Find peers
candidate_peers = SECTOR_PEERS.get(sector, [])
# Remove selected ticker from peers list
candidate_peers = [p for p in candidate_peers if p.upper() != ticker.upper()][:7]
peers = [ticker.upper()] + candidate_peers

st.info(f"Comparing {ticker} against {len(candidate_peers)} sector peers. Fetching data …")

# ── FETCH PEER DATA ───────────────────────────────────────────────────────────
progress = st.progress(0)
rows = []
for i, sym in enumerate(peers):
    progress.progress((i + 1) / len(peers), text=f"Fetching {sym} …")
    try:
        info_i = get_ticker_info(sym)
        if not info_i:
            continue
        price    = safe_get(info_i, 'currentPrice') or safe_get(info_i, 'regularMarketPrice')
        mktcap   = safe_get(info_i, 'marketCap')
        pe       = safe_get(info_i, 'trailingPE')
        ps       = safe_get(info_i, 'priceToSalesTrailing12Months')
        eps_g    = safe_get(info_i, 'earningsGrowth')
        rev_g    = safe_get(info_i, 'revenueGrowth')
        pm       = safe_get(info_i, 'profitMargins')
        roe      = safe_get(info_i, 'returnOnEquity')
        beta     = safe_get(info_i, 'beta')
        name     = safe_get(info_i, 'shortName', sym)

        rows.append({
            '_ticker': sym,
            '_is_selected': sym.upper() == ticker.upper(),
            'Ticker': sym,
            'Company': (name or '')[:20],
            'Price': price,
            'Mkt Cap': mktcap,
            'P/E': pe,
            'P/S': ps,
            'EPS Growth': eps_g,
            'Rev Growth': rev_g,
            'Profit Margin': pm,
            'ROE': roe,
            'Beta': beta,
        })
    except Exception:
        pass

progress.empty()

if not rows:
    st.error("Could not load peer data.")
    st.stop()

df = pd.DataFrame(rows)

# ── COLOR CODING HELPERS ──────────────────────────────────────────────────────
def best_worst_colors(series, higher_is_better=True):
    """Return dict {idx: color} marking best=green, worst=red."""
    valid = series.dropna()
    if valid.empty:
        return {}
    best  = valid.idxmax() if higher_is_better else valid.idxmin()
    worst = valid.idxmin() if higher_is_better else valid.idxmax()
    result = {}
    if best == worst:
        return result
    result[best]  = '#00FF41'
    result[worst] = '#FF4444'
    return result

metric_dir = {
    'P/E': False,  # lower is better
    'P/S': False,
    'EPS Growth': True,
    'Rev Growth': True,
    'Profit Margin': True,
    'ROE': True,
    'Beta': False,
}

color_maps = {}
for m, higher in metric_dir.items():
    if m in df.columns:
        color_maps[m] = best_worst_colors(df[m], higher)

# ── RENDER TABLE ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Peer Comparison Table</div>', unsafe_allow_html=True)

sort_col = st.selectbox("Sort by", ['Mkt Cap', 'P/E', 'EPS Growth', 'Rev Growth', 'Profit Margin', 'ROE'])
ascending = st.checkbox("Ascending", value=False)
if sort_col in df.columns:
    df = df.sort_values(sort_col, ascending=ascending, na_position='last')

html = """<div style="overflow-x:auto;"><table class="peer-table">
<thead><tr>
  <th style="text-align:left">Ticker</th>
  <th style="text-align:left">Company</th>
  <th>Price</th><th>Mkt Cap</th><th>P/E</th><th>P/S</th>
  <th>EPS Growth</th><th>Rev Growth</th><th>Margin</th><th>ROE</th><th>Beta</th>
</tr></thead><tbody>"""

for i, row in df.iterrows():
    selected = row['_is_selected']
    row_class = 'selected-row' if selected else ''
    row_style = 'background:#0D2010;border-left:3px solid #00FF41;' if selected else ''

    def cell(val, metric=None, is_pct=False, is_price=False, is_large=False):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return '<span style="color:#444">—</span>'
        v = float(val)
        color = '#FFFFFF'
        if metric and metric in color_maps:
            color = color_maps[metric].get(i, '#FFFFFF')
        if is_price:   return f'<span style="color:{color}">${v:,.2f}</span>'
        if is_large:   return f'<span style="color:{color}">{fmt_large_number(v)}</span>'
        if is_pct:     return f'<span style="color:{color}">{v*100:.1f}%</span>'
        return f'<span style="color:{color}">{v:.2f}</span>'

    html += f'<tr style="{row_style}">'
    html += f'<td style="color:#00FF41;font-weight:bold">{row["Ticker"]}</td>'
    html += f'<td style="color:#AAAAAA">{row["Company"]}</td>'
    html += f'<td>{cell(row["Price"], is_price=True)}</td>'
    html += f'<td>{cell(row["Mkt Cap"], is_large=True)}</td>'
    html += f'<td>{cell(row["P/E"], metric="P/E")}</td>'
    html += f'<td>{cell(row["P/S"], metric="P/S")}</td>'
    html += f'<td>{cell(row["EPS Growth"], metric="EPS Growth", is_pct=True)}</td>'
    html += f'<td>{cell(row["Rev Growth"], metric="Rev Growth", is_pct=True)}</td>'
    html += f'<td>{cell(row["Profit Margin"], metric="Profit Margin", is_pct=True)}</td>'
    html += f'<td>{cell(row["ROE"], metric="ROE", is_pct=True)}</td>'
    html += f'<td>{cell(row["Beta"], metric="Beta")}</td>'
    html += '</tr>'

html += "</tbody></table></div>"
html += '<div style="font-size:11px;color:#555;margin-top:6px;font-family:monospace;">🟢 Best in group &nbsp;&nbsp; 🔴 Worst in group &nbsp;&nbsp; ★ Selected ticker</div>'
st.markdown(html, unsafe_allow_html=True)

# ── CSV EXPORT ────────────────────────────────────────────────────────────────
export_df = df.drop(columns=['_ticker', '_is_selected'], errors='ignore')
csv = export_df.to_csv(index=False)
st.download_button("⬇ Export to CSV", csv, f"{ticker}_peers.csv", "text/csv")

st.caption("Source: yfinance · 24h cache · Peers auto-selected by sector")
