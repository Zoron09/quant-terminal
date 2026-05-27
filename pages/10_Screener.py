import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
from utils.code33_engine import get_code33_data, CACHE_VERSION

st.set_page_config(
    page_title="Screener · Quant Terminal",
    page_icon="●",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stSidebar"],
[data-testid="collapsedControl"]
{ visibility: hidden !important; height: 0 !important; display: none !important; }
.stApp { background: #0E0E10 !important; padding: 0 !important; }
.block-container { padding: 0 !important; max-width: 100% !important; margin: 0 !important; }
iframe { border: none !important; width: 100% !important; }
</style>
""", unsafe_allow_html=True)

def run_code33(tickers_df):
    winners = []
    total = len(tickers_df)
    progress = st.progress(0, text="Starting Code 33 scan...")
    
    sector_map = {}
    if 'Symbol' in tickers_df.columns and 'Sector' in tickers_df.columns:
        sector_map = dict(zip(
            tickers_df['Symbol'].str.upper(),
            tickers_df['Sector'].fillna('Unknown')
        ))
    
    mcap_map = {}
    if 'Symbol' in tickers_df.columns and 'Market capitalization' in tickers_df.columns:
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                if v >= 1e6:  return f"${v/1e6:.1f}M"
                return f"${v:,.0f}"
            except: return "N/A"
        mcap_map = {
            str(row['Symbol']).upper(): fmt_mcap(row['Market capitalization'])
            for _, row in tickers_df.iterrows()
            if 'Market capitalization' in tickers_df.columns
        }

    tickers = tickers_df['Symbol'].str.upper().tolist() \
        if 'Symbol' in tickers_df.columns else []

    insufficient = 0
    for i, ticker in enumerate(tickers):
        progress.progress(
            (i + 1) / total,
            text=f"Analysing {i+1} of {total} — {ticker}"
        )
        try:
            data = get_code33_data(ticker, CACHE_VERSION)
            if not data:
                insufficient += 1
                continue

            status = data.get('status', 'insufficient')
            if status not in ('green', 'yellow'):
                if status == 'insufficient':
                    insufficient += 1
                continue

            def safe3(lst):
                if not lst: return [0, 0, 0]
                lst = [x for x in lst if x is not None]
                if len(lst) < 3: lst = ([0] * (3 - len(lst))) + lst
                return [round(x, 1) for x in lst[-3:]]

            eps_rates  = data.get('eps_yoy_final', [])
            rev_rates  = data.get('rev_yoy_final', [])
            margin_vals = data.get('npm_vals', [])

            winners.append({
                'ticker':  ticker,
                'company': data.get('company_name', ticker),
                'sector':  sector_map.get(ticker, 'Unknown'),
                'mcap':    mcap_map.get(ticker, 'N/A'),
                'eps':     safe3(eps_rates),
                'rev':     safe3(rev_rates),
                'margin':  safe3(margin_vals),
                'status':  status,
            })
        except Exception as e:
            insufficient += 1
            continue

    progress.empty()
    return winners, insufficient

# ── Read HTML template ──────────────────────────────────────────
with open("frontend/screener.html", "r", encoding="utf-8") as f:
    html_template = f.read()

# ── Session state ───────────────────────────────────────────────
if 'winners' not in st.session_state:
    st.session_state.winners = None
if 'scan_meta' not in st.session_state:
    st.session_state.scan_meta = None

# ── Hidden file uploader + run trigger ─────────────────────────
# These Streamlit widgets are invisible (CSS hidden above)
# but they process the actual file and engine run server-side.
# The visible UI comes entirely from the HTML iframe below.

with st.container():
    st.markdown("""
    <style>
    [data-testid="stFileUploader"],
    [data-testid="stFileUploaderDropzone"],
    div[data-testid="stHorizontalBlock"],
    .stFileUploader, .stButton,
    section[data-testid="stFileUploadDropzone"]
    { display: none !important; visibility: hidden !important; 
      height: 0 !important; overflow: hidden !important; }
    </style>
    """, unsafe_allow_html=True)
    
    uploaded = st.file_uploader(
        "csv", type="csv", 
        key="csv_upload",
        label_visibility="collapsed"
    )
    if uploaded and st.button("Run", key="run_btn"):
        df = pd.read_csv(uploaded)
        winners, insufficient = run_code33(df)
        st.session_state.winners = winners
        st.session_state.scan_meta = {
            'total': len(df),
            'passed': len(winners),
            'insufficient': insufficient,
            'filename': uploaded.name,
        }

# ── Inject real data into HTML ──────────────────────────────────
html = html_template

if st.session_state.winners is not None:
    meta = st.session_state.scan_meta
    winners_json = json.dumps(st.session_state.winners)
    
    # Replace hardcoded WINNERS array with real data
    inject = f"""
    <script>
    window.__REAL_WINNERS__ = {winners_json};
    window.__REAL_META__ = {json.dumps(meta)};
    </script>
    """
    # Inject before closing </head>
    html = html.replace('</head>', inject + '</head>')

components.html(html, height=1000, scrolling=True)

col1, col2, col3 = st.columns([1,1,1])
with col1:
    if st.button("→ Overview"):
        st.switch_page("pages/15_stock_detail.py")
with col2:
    if st.button("→ Portfolio"):
        st.switch_page("pages/12_Portfolio.py")
