"""
Tab 10 — Stock Screener  (SQLite-backed instant results)

Scan architecture:
  First scan  — Alpaca fast scan (~2-3 min) → auto-enrich top 200 with yfinance
                → persist everything to SQLite
  All subsequent loads — query SQLite (<3 sec, instant)

India — yfinance throughout, same SQLite persistence.
"""
import streamlit as st
import sys, os, json, time
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.data_fetcher import get_price_history, get_ticker_info
from utils.sepa_engine import (
    compute_trend_template, compute_stage, compute_rs,
    detect_vcp, compute_sepa_score, compute_earnings_acceleration,
)
from utils.formatters import safe_get
from utils.screener_db import (
    upsert_rows, load_market, freshness, clear_market, row_count,
)

try:
    from utils.alpaca_client import (
        get_all_us_symbols, get_snapshots,
        fetch_bars_batch, get_bars_bulk,
        get_stream_manager, _HAS_ALPACA,
    )
except Exception:
    _HAS_ALPACA = False
    get_all_us_symbols = get_snapshots = fetch_bars_batch = None
    get_bars_bulk = get_stream_manager = None

st.set_page_config(page_title="Screener · Quant Terminal", page_icon="🔍", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

DARK   = '#0E1117'
GREEN  = '#00FF41'
RED    = '#FF4444'
YELLOW = '#FFD700'
GRAY   = '#888888'
BLUE   = '#00BFFF'
_base  = os.path.dirname(os.path.dirname(__file__))

render_sidebar()
st.markdown("## 🔍 Stock Screener")

# ── Data source badge ─────────────────────────────────────────────────────────
if _HAS_ALPACA:
    st.markdown(
        f'<div style="background:#0d2818;border:1px solid {GREEN};border-radius:4px;'
        f'padding:5px 14px;display:inline-block;font-family:monospace;font-size:12px;'
        f'color:{GREEN};margin-bottom:8px;">▶ ALPACA IEX — Real-time · Full US market</div>',
        unsafe_allow_html=True,
    )
else:
    st.warning("Alpaca credentials not configured — falling back to yfinance (slower).")


# ── NaN-safe helpers ──────────────────────────────────────────────────────────

def _safe_int(v) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else int(f)
    except (TypeError, ValueError):
        return None


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _safe_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).lower() in ('1', 'true', 'yes')


# ── Universe loaders ──────────────────────────────────────────────────────────

@st.cache_data(ttl=86400)
def _load_india_universe() -> list[str]:
    path = os.path.join(_base, 'data', 'nifty500_tickers.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


@st.cache_data(ttl=86400)
def _load_sp500_fallback() -> list[str]:
    path = os.path.join(_base, 'data', 'sp500_tickers.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


# ── Core SEPA row builder ─────────────────────────────────────────────────────

def _compute_row(
    symbol: str,
    df: pd.DataFrame,
    bench_df: pd.DataFrame,
    info: dict | None = None,
    snap: dict | None = None,
) -> dict | None:
    try:
        if df is None or df.empty or len(df) < 100:
            return None

        trend = compute_trend_template(df)
        if trend.get('pass_count', 0) < 8:
            return None
        stage = compute_stage(df)
        rs    = compute_rs(df, bench_df)
        vcp   = detect_vcp(df, lookback=90)

        close    = df['Close'].dropna()
        price    = float(snap['price']) if snap and snap.get('price') else float(close.iloc[-1])
        prev     = float(snap['prev_close']) if snap and snap.get('prev_close') else (
                   float(close.iloc[-2]) if len(close) > 1 else price)
        chg_pct  = float(snap['change_pct']) if snap and snap.get('change_pct') is not None else (
                   round((price - prev) / prev * 100, 2) if prev else 0.0)

        hi52 = float(close.tail(252).max())
        lo52 = float(close.tail(252).min())

        vol       = df['Volume'].dropna()
        avg_vol_30 = float(vol.tail(30).mean()) if len(vol) >= 30 else float(vol.mean())
        if avg_vol_30 < 100000:
            return None

        avg_vol   = float(vol.rolling(50).mean().iloc[-1]) if len(vol) >= 50 else float(vol.mean())
        last_vol  = int(snap['volume']) if snap and snap.get('volume') else int(vol.iloc[-1])
        vol_ratio = round(last_vol / avg_vol, 1) if avg_vol > 0 else 0.0

        composite = compute_sepa_score(
            trend, stage, rs, vcp,
            {'accelerating': False, 'growth_rates': [], 'latest_growth': None},
            df,
            earnings_fetched=False,
        )

        mc    = safe_get(info, 'marketCap')      if info else None
        pe    = safe_get(info, 'trailingPE')     if info else None
        pm    = safe_get(info, 'profitMargins')  if info else None
        rev_g = safe_get(info, 'revenueGrowth')  if info else None
        eps_g = safe_get(info, 'earningsGrowth') if info else None
        name  = ((safe_get(info, 'longName') or safe_get(info, 'shortName') or symbol)
                 if info else symbol)
        name  = (name[:28] + '\u2026') if len(name) > 28 else name

        return {
            'ticker':          symbol,
            'name':            name,
            'price':           price,
            'chg_pct':         chg_pct,
            'hi52':            hi52,
            'lo52':            lo52,
            'pct_from_hi':     round((price / hi52 - 1) * 100, 1) if hi52 else None,
            'market_cap':      mc,
            'pe':              pe,
            'profit_margin':   pm,
            'rev_growth':      rev_g,
            'eps_growth':      eps_g,
            'vol_ratio':       vol_ratio,
            'volume':          last_vol,
            'trend_pass':      trend.get('pass_count', 0),
            'stage':           stage.get('stage', 0),
            'stage_label':     stage.get('label', 'N/A'),
            'rs_12m':          rs.get('rs_pct_12m'),
            'vcp':             vcp.get('vcp_detected', False),
            'sepa_score':      composite['total'],
            'sepa_grade':      composite['grade'],
            'earnings_status': 'Pending',
        }
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def _yf_snapshot(ticker: str) -> dict | None:
    try:
        df = get_price_history(ticker, period='2y', interval='1d')
        if df is None or df.empty or len(df) < 100:
            return None
        info     = get_ticker_info(ticker)
        bench    = '^NSEI' if '.' in ticker else '^GSPC'
        bench_df = get_price_history(bench, period='2y', interval='1d')
        return _compute_row(ticker, df, bench_df, info)
    except Exception:
        return None


# ── Auto-enrich top N survivors with yfinance earnings + fundamentals ─────────

def _enrich_and_store(rows: list[dict], market: str, n: int = 200):
    """
    Fetch quarterly EPS + fundamentals for top-N rows by SEPA score.
    Recalculates SEPA score with earnings_fetched=True.
    Upserts ALL rows to SQLite (unenriched tail gets Pending status).
    """
    import yfinance as _yf

    # Sort by score, enrich top N
    rows_sorted = sorted(rows, key=lambda r: r.get('sepa_score', 0), reverse=True)
    to_enrich   = rows_sorted[:n]
    tail        = rows_sorted[n:]

    bar_enrich = st.progress(0.0, text=f"Auto-enriching top {len(to_enrich)} results with earnings data…")

    for idx, row in enumerate(to_enrich):
        sym = row['ticker']
        bar_enrich.progress((idx + 1) / len(to_enrich),
                            text=f"Enriching {sym} ({idx+1}/{len(to_enrich)})…")
        try:
            # Fundamentals
            info = get_ticker_info(sym)
            if info:
                row['market_cap']  = safe_get(info, 'marketCap')   or row.get('market_cap')
                row['pe']          = safe_get(info, 'trailingPE')   or row.get('pe')
                row['profit_margin'] = safe_get(info, 'profitMargins') or row.get('profit_margin')
                row['rev_growth']  = safe_get(info, 'revenueGrowth')  or row.get('rev_growth')
                row['eps_growth']  = safe_get(info, 'earningsGrowth') or row.get('eps_growth')
                raw_name = safe_get(info, 'longName') or safe_get(info, 'shortName') or sym
                row['name'] = (raw_name[:28] + '…') if len(raw_name) > 28 else raw_name

            # Quarterly EPS for earnings acceleration
            eps_list = []
            try:
                t     = _yf.Ticker(sym)
                q_inc = t.quarterly_financials
                if q_inc is not None and not q_inc.empty:
                    for key in ['Basic EPS', 'Diluted EPS', 'EPS', 'basicEps', 'dilutedEps']:
                        if key in q_inc.index:
                            eps_row = q_inc.loc[key]
                            eps_list = list(reversed([
                                float(v) if v is not None
                                   and not (isinstance(v, float) and np.isnan(v))
                                else None
                                for v in eps_row.values
                            ]))
                            break
            except Exception:
                pass

            ea = compute_earnings_acceleration(eps_list)

            # Re-score with earnings data
            trend_stub = {'pass_count': row.get('trend_pass', 0)}
            rs_stub    = {'rs_pct_12m': row.get('rs_12m')}
            vcp_stub   = {'vcp_detected': bool(row.get('vcp', False)), 'contractions': 0}
            stage_stub = {'stage': row.get('stage', 0)}

            new_comp = compute_sepa_score(
                trend_stub, stage_stub, rs_stub, vcp_stub, ea,
                earnings_fetched=True,
            )
            row['sepa_score']      = new_comp['total']
            row['sepa_grade']      = new_comp['grade']
            row['earnings_status'] = new_comp['earnings_status']

        except Exception:
            row['earnings_status'] = 'No Data'

    bar_enrich.empty()

    # Write everything to SQLite
    all_rows = to_enrich + tail
    upsert_rows(all_rows, market)
    return all_rows


# ── UI — Market selector and scan options ─────────────────────────────────────
col_mkt, col_vcp = st.columns([2, 1])
with col_mkt:
    market = st.selectbox("Market Universe",
                          ['US (Full Market ~6000 stocks)', 'India (Nifty 500)'], index=0)
is_us = market.startswith('US')
mkt_key = 'US' if is_us else 'India'

with col_vcp:
    st.markdown("<br>", unsafe_allow_html=True)
    st.checkbox("VCP detected only", key='f_vcp')

st.markdown("---")

# ── Action buttons + freshness label ─────────────────────────────────────────
btn_col, refresh_col, info_col = st.columns([2, 1, 3])

run_scan    = btn_col.button("RUN SCAN", type="primary", use_container_width=True,
                             help="Full Alpaca scan (~2-3 min). Results cached in SQLite.")
do_refresh  = refresh_col.button("⟳ Refresh Data", use_container_width=True,
                                  help="Re-run scan and rebuild database.")

# Freshness label
age_s = freshness(mkt_key)
if age_s is not None:
    age_min = age_s / 60
    if age_min < 1:
        fresh_str = "< 1 min ago"
    elif age_min < 60:
        fresh_str = f"{age_min:.0f} min ago"
    else:
        fresh_str = f"{age_min/60:.1f}h ago"
    n_cached = row_count(mkt_key)
    info_col.markdown(
        f'<div style="color:{GREEN};font-size:12px;font-family:monospace;padding-top:8px;">'
        f'⚡ SQLite cache: {n_cached:,} stocks &nbsp;·&nbsp; '
        f'Data freshness: {fresh_str}</div>',
        unsafe_allow_html=True,
    )
else:
    info_col.markdown(
        f'<div style="color:{YELLOW};font-size:12px;font-family:monospace;padding-top:8px;">'
        f'No cache yet — click RUN SCAN to build database.</div>',
        unsafe_allow_html=True,
    )

trigger_scan = run_scan or do_refresh

# ── FULL US MARKET SCAN (Alpaca) ──────────────────────────────────────────────
if trigger_scan and is_us and _HAS_ALPACA:
    clear_market(mkt_key)
    scan_start_ts = time.time()
    results       = []

    ph0 = st.empty()
    ph0.info("Phase 0/3 — Loading US stock universe from Alpaca…")
    t0 = time.time()
    all_symbols = get_all_us_symbols()
    ph0.success(
        f"Phase 0 complete — {len(all_symbols):,} tradeable US stocks "
        f"({time.time()-t0:.1f}s, cached 24h)"
    )

    if not all_symbols:
        st.error("Could not load asset universe from Alpaca.")
        st.stop()

    ph1 = st.empty()
    n_snap_batches = (len(all_symbols) + 999) // 1000
    ph1.info(
        f"Phase 1/3 — Fetching real-time prices for {len(all_symbols):,} symbols "
        f"({n_snap_batches} API calls)…"
    )
    t1        = time.time()
    snapshots = get_snapshots(tuple(all_symbols))

    min_price = 12.0
    min_vol = 100000
    scan_symbols = [
        sym for sym, snap in snapshots.items()
        if snap.get('price') and snap['price'] >= min_price
        and (snap.get('volume') or 0) >= min_vol
    ]
    ph1.success(
        f"Phase 1 complete — {len(snapshots):,} prices fetched in {time.time()-t1:.1f}s  "
        f"·  {len(scan_symbols):,} pass price/volume pre-filter"
    )

    if not scan_symbols:
        st.warning("No symbols pass the price/volume pre-filter. Try lowering thresholds.")
        st.stop()

    batch_size    = 500
    bar_start     = datetime.now() - timedelta(days=370)
    bench_df      = get_price_history('^GSPC', period='2y', interval='1d')
    total_batches = (len(scan_symbols) + batch_size - 1) // batch_size
    prog          = st.progress(0.0)
    ph23          = st.empty()
    skipped       = 0

    for batch_i in range(total_batches):
        batch = scan_symbols[batch_i * batch_size: (batch_i + 1) * batch_size]
        done  = batch_i * batch_size
        pct   = done / len(scan_symbols)
        elapsed = time.time() - scan_start_ts
        eta_str = ''
        if pct > 0.05:
            eta_sec = elapsed / pct * (1 - pct)
            eta_str = f'  ·  ETA {eta_sec:.0f}s'
        prog.progress(
            min(pct, 1.0),
            text=(f"Phase 2+3/3 — Batch {batch_i+1}/{total_batches}: "
                  f"bars + SEPA for {len(batch)} symbols "
                  f"({done:,}/{len(scan_symbols):,}{eta_str})"),
        )
        bars_dict = fetch_bars_batch(batch, start=bar_start)
        for sym in batch:
            df   = bars_dict.get(sym)
            snap = snapshots.get(sym)
            if df is None or df.empty:
                skipped += 1
                continue
            row = _compute_row(sym, df, bench_df, snap=snap)
            if row:
                results.append(row)

    prog.empty()
    total_time = time.time() - scan_start_ts
    ph23.success(
        f"Scan complete — {len(results):,} stocks with SEPA data  "
        f"·  {skipped:,} skipped  ·  {total_time:.0f}s"
    )

    # Auto-enrich top 200 + write to SQLite
    st.info("Auto-enriching top 200 survivors with earnings + fundamentals…")
    results = _enrich_and_store(results, mkt_key, n=200)

    st.session_state['scan_results'] = results
    st.session_state['scan_market']  = mkt_key
    st.session_state['scan_ts']      = scan_start_ts
    st.session_state['scan_count']   = len(scan_symbols)
    st.success(f"Database updated — {len(results):,} stocks stored in SQLite.")


# ── INDIA / yfinance SCAN ─────────────────────────────────────────────────────
elif trigger_scan and not is_us:
    clear_market(mkt_key)
    universe = _load_india_universe()
    if not universe:
        st.error("India universe file not found.")
        st.stop()

    bench_df = get_price_history('^NSEI', period='2y', interval='1d')
    results  = []
    bar      = st.progress(0.0, text="Scanning India universe…")
    for i, sym in enumerate(universe):
        bar.progress((i + 1) / len(universe), text=f"Scanning {sym} ({i+1}/{len(universe)})")
        row = _yf_snapshot(sym)
        if row:
            results.append(row)
    bar.empty()
    st.success(f"India scan complete — {len(results)} stocks.")

    st.info("Auto-enriching top 200 with earnings data…")
    results = _enrich_and_store(results, mkt_key, n=200)

    st.session_state['scan_results'] = results
    st.session_state['scan_market']  = mkt_key
    st.session_state['scan_ts']      = time.time()
    st.session_state['scan_count']   = len(universe)
    st.success(f"Database updated — {len(results)} stocks stored.")


# ── yfinance US FALLBACK (no Alpaca) ─────────────────────────────────────────
elif trigger_scan and is_us and not _HAS_ALPACA:
    clear_market(mkt_key)
    universe = _load_sp500_fallback()
    bench_df = get_price_history('^GSPC', period='2y', interval='1d')
    results  = []
    bar      = st.progress(0.0)
    for i, sym in enumerate(universe):
        bar.progress((i + 1) / len(universe), text=f"{sym} ({i+1}/{len(universe)})")
        row = _yf_snapshot(sym)
        if row:
            results.append(row)
    bar.empty()

    st.info("Auto-enriching top 200 with earnings data…")
    results = _enrich_and_store(results, mkt_key, n=200)

    st.session_state['scan_results'] = results
    st.session_state['scan_market']  = mkt_key
    st.session_state['scan_ts']      = time.time()
    st.session_state['scan_count']   = len(universe)
    st.success(f"Scan complete — {len(results)} stocks (yfinance fallback).")


# ── Load from SQLite if session is empty (instant on revisit) ─────────────────
if 'scan_results' not in st.session_state or \
        st.session_state.get('scan_market') != mkt_key:
    cached_df = load_market(mkt_key)
    if not cached_df.empty:
        st.session_state['scan_results'] = cached_df.to_dict('records')
        st.session_state['scan_market']  = mkt_key
        st.session_state['scan_count']   = len(cached_df)


# ── Show results ──────────────────────────────────────────────────────────────
raw = st.session_state.get('scan_results', [])

if not raw:
    st.info(
        "No cached data yet. Click **RUN SCAN** to build the database.\n\n"
        "**First scan:** ~2-3 min (Alpaca) or ~10-15 min (yfinance).  "
        "All subsequent loads are instant from SQLite."
    )
    st.stop()

# Ensure all rows have earnings_status
for _r in raw:
    if 'earnings_status' not in _r:
        _r['earnings_status'] = 'Pending'

df_res = pd.DataFrame(raw)

# ── Apply post-scan filters ───────────────────────────────────────────────────
m = pd.Series([True] * len(df_res))

f_vcp = st.session_state.get('f_vcp', False)

if f_vcp:
    m &= df_res['vcp'].apply(_safe_bool)

filtered = df_res[m].sort_values(
    'sepa_score', ascending=False, key=lambda s: pd.to_numeric(s, errors='coerce').fillna(0)
).reset_index(drop=True)

total_scanned = st.session_state.get('scan_count', len(raw))
st.markdown(
    f"### {len(filtered):,} stocks match &nbsp;·&nbsp; "
    f"<span style='color:{GRAY};font-size:14px;'>"
    f"{total_scanned:,} scanned &nbsp;·&nbsp; {len(raw):,} with SEPA data</span>",
    unsafe_allow_html=True,
)

if filtered.empty:
    st.warning("No stocks match the current filters. Try relaxing the criteria.")
    st.stop()

# ── Live WebSocket section ────────────────────────────────────────────────────
if _HAS_ALPACA and not filtered.empty and is_us:
    stream_syms = filtered['ticker'].tolist()[:200]
    mgr = get_stream_manager()

    live_hdr, ctrl = st.columns([5, 1])
    with ctrl:
        if mgr.is_running():
            if st.button("Stop Live Feed", use_container_width=True):
                mgr.stop(); st.rerun()
            st.markdown(f'<div style="color:{GREEN};font-size:11px;font-family:monospace;">● STREAMING</div>',
                        unsafe_allow_html=True)
        else:
            if st.button("Start Live Feed", type="primary", use_container_width=True,
                         help=f"Stream 1-min bars for top {len(stream_syms)} results"):
                mgr.start(stream_syms); st.rerun()
    with live_hdr:
        if mgr.is_running() and mgr.prices:
            updates = []
            for sym in stream_syms:
                lp = mgr.prices.get(sym)
                if lp:
                    old   = filtered.loc[filtered['ticker'] == sym, 'price']
                    old_p = _safe_float(old.iloc[0]) if not old.empty else None
                    chg   = round((lp['price'] - old_p) / old_p * 100, 2) if old_p else 0
                    updates.append({'Ticker': sym, 'Live': f"${lp['price']:.2f}",
                                    'Chg': f"{chg:+.2f}%", 'High': f"${lp['high']:.2f}",
                                    'Low': f"${lp['low']:.2f}", 'Vol': f"{lp['volume']:,}"})
            if updates:
                st.dataframe(pd.DataFrame(updates), use_container_width=True, hide_index=True)
                if st.button("Refresh Live Prices"):
                    st.rerun()

# ── Results table ─────────────────────────────────────────────────────────────

def _chg_html(v) -> str:
    fv = _safe_float(v)
    if fv is None:
        return '<span style="color:#444">N/A</span>'
    c = GREEN if fv >= 0 else RED
    return f'<span style="color:{c}">{fv:+.2f}%</span>'


def _mc_html(v) -> str:
    fv = _safe_float(v)
    if fv is None:
        return '<span style="color:#444">—</span>'
    if fv >= 1e12: return f"${fv/1e12:.1f}T"
    if fv >= 1e9:  return f"${fv/1e9:.1f}B"
    if fv >= 1e6:  return f"${fv/1e6:.1f}M"
    return f"${fv:,.0f}"


rows_html = ""
live_prices_map = (get_stream_manager().prices or {}) if _HAS_ALPACA else {}

for _, row in filtered.iterrows():
    sym = row['ticker']

    # NaN-safe conversions for every numeric field used in display
    rs_val    = _safe_float(row.get('rs_12m'))
    sepa_sc   = _safe_float(row.get('sepa_score')) or 0.0
    trend_val = _safe_int(row.get('trend_pass'))
    stage_val = _safe_int(row.get('stage')) or 0
    vol_r     = _safe_float(row.get('vol_ratio')) or 0.0
    price_val = _safe_float(row.get('price')) or 0.0
    pe_val    = _safe_float(row.get('pe'))

    rs_c   = (GREEN  if rs_val and rs_val >= 70
              else YELLOW if rs_val and rs_val >= 50
              else RED)
    rs_str = (f'<span style="color:{rs_c}">{int(rs_val)}</span>'
              if rs_val is not None
              else '<span style="color:#444">—</span>')

    vcp_s    = f'<span style="color:{GREEN}">VCP</span>' if _safe_bool(row.get('vcp')) else '<span style="color:#333">—</span>'
    sc_c     = GREEN if sepa_sc >= 70 else (YELLOW if sepa_sc >= 50 else RED)
    grade    = str(row.get('sepa_grade', 'D') or 'D')
    gc       = {'A': GREEN, 'B': '#7FFF00', 'C': YELLOW, 'D': RED}.get(grade, GRAY)
    trend_c  = (GREEN  if trend_val is not None and trend_val >= 7
                else YELLOW if trend_val is not None and trend_val >= 5
                else RED)
    trend_s  = f"{trend_val}/8" if trend_val is not None else "—"
    stage_c  = {2: GREEN, 1: GRAY, 3: YELLOW, 4: RED}.get(stage_val, GRAY)
    stage_lbl = str(row.get('stage_label', 'N/A') or 'N/A').split('—')[0].strip()
    pe_str   = (f"{pe_val:.1f}"
                if pe_val is not None
                else '<span style="color:#444">—</span>')

    earn_s   = str(row.get('earnings_status', 'Pending') or 'Pending')
    earn_c   = (GREEN  if earn_s == 'Accelerating'
                else RED    if earn_s == 'Not Accelerating'
                else YELLOW if earn_s == 'No Data'
                else GRAY)

    lp       = live_prices_map.get(sym)
    live_tag = (f' <span style="color:{BLUE};font-size:10px;">[{lp["price"]:.2f} live]</span>'
                if lp else '')

    rows_html += f"""
<tr>
  <td><a href="?ticker={sym}" style="color:{GREEN};font-weight:bold;
      font-family:monospace;text-decoration:none;">{sym}</a>{live_tag}</td>
  <td style="color:#CCC;font-size:12px;">{row.get('name', sym)}</td>
  <td style="font-family:monospace;">${price_val:.2f}</td>
  <td>{_chg_html(row.get('chg_pct'))}</td>
  <td style="font-family:monospace;">{_mc_html(row.get('market_cap'))}</td>
  <td style="font-family:monospace;">{pe_str}</td>
  <td style="font-family:monospace;color:{YELLOW};">{vol_r:.1f}x</td>
  <td>{rs_str}</td>
  <td><span style="color:{trend_c}">{trend_s}</span></td>
  <td><span style="color:{stage_c}">{stage_lbl}</span></td>
  <td>{vcp_s}</td>
  <td style="font-family:monospace;color:{earn_c};font-size:11px;">{earn_s}</td>
  <td style="font-family:monospace;color:{sc_c};">{sepa_sc:.0f}</td>
  <td><b style="color:{gc};">{grade}</b></td>
</tr>"""

st.markdown(f"""
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead>
<tr style="background:#161B22;color:{GRAY};text-transform:uppercase;font-size:10px;
           border-bottom:1px solid #333;letter-spacing:1px;font-family:monospace;">
  <th style="padding:8px 6px;text-align:left;">Ticker</th>
  <th style="padding:8px 6px;text-align:left;">Company</th>
  <th style="padding:8px 6px;text-align:right;">Price</th>
  <th style="padding:8px 6px;text-align:right;">Chg%</th>
  <th style="padding:8px 6px;text-align:right;">Mkt Cap</th>
  <th style="padding:8px 6px;text-align:right;">P/E</th>
  <th style="padding:8px 6px;text-align:right;">Vol Ratio</th>
  <th style="padding:8px 6px;text-align:right;">RS(12M)</th>
  <th style="padding:8px 6px;text-align:center;">Trend</th>
  <th style="padding:8px 6px;text-align:center;">Stage</th>
  <th style="padding:8px 6px;text-align:center;">VCP</th>
  <th style="padding:8px 6px;text-align:center;">Earnings</th>
  <th style="padding:8px 6px;text-align:right;">SEPA</th>
  <th style="padding:8px 6px;text-align:center;">Grade</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>""", unsafe_allow_html=True)

# ── Export ────────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
ec1, ec2 = st.columns([1, 4])
_csv_cols = ['ticker', 'name', 'price', 'chg_pct', 'vol_ratio', 'rs_12m',
             'trend_pass', 'stage', 'vcp', 'earnings_status', 'sepa_score', 'sepa_grade',
             'market_cap', 'pe', 'profit_margin', 'rev_growth', 'eps_growth']
_csv_cols = [c for c in _csv_cols if c in filtered.columns]
csv_df = filtered[_csv_cols].copy()
ec1.download_button(
    "Export CSV",
    data=csv_df.to_csv(index=False),
    file_name=f"screener_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
    mime='text/csv',
)

# ── Distribution charts ───────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Distribution")
ch1, ch2, ch3 = st.columns(3)

with ch1:
    gc2 = filtered['sepa_grade'].value_counts().reindex(['A', 'B', 'C', 'D'], fill_value=0)
    fig = go.Figure(go.Bar(
        x=gc2.index.tolist(), y=gc2.values.tolist(),
        marker_color=[GREEN, '#7FFF00', YELLOW, RED],
        text=gc2.values.tolist(), textposition='outside', textfont_color='white',
    ))
    fig.update_layout(
        paper_bgcolor=DARK, plot_bgcolor='#161B22', height=220,
        margin=dict(t=30, b=10, l=10, r=10),
        title=dict(text='SEPA Grade Distribution', font=dict(color=GRAY, size=12)),
        xaxis=dict(color=GRAY), yaxis=dict(color=GRAY, gridcolor='#222'),
        font=dict(color='white', family='Courier New'), showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

with ch2:
    sc2 = pd.to_numeric(filtered['sepa_score'], errors='coerce').dropna()
    fig2 = go.Figure(go.Histogram(
        x=sc2, nbinsx=20,
        marker_color=BLUE, opacity=0.8,
    ))
    fig2.update_layout(
        paper_bgcolor=DARK, plot_bgcolor='#161B22', height=220,
        margin=dict(t=30, b=10, l=10, r=10),
        title=dict(text='SEPA Score Distribution', font=dict(color=GRAY, size=12)),
        xaxis=dict(color=GRAY), yaxis=dict(color=GRAY, gridcolor='#222'),
        font=dict(color='white', family='Courier New'), showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

with ch3:
    earn_counts = filtered['earnings_status'].value_counts() if 'earnings_status' in filtered.columns else pd.Series()
    if not earn_counts.empty:
        earn_colors = [
            GREEN  if e == 'Accelerating'     else
            RED    if e == 'Not Accelerating'  else
            YELLOW if e == 'No Data'           else GRAY
            for e in earn_counts.index
        ]
        fig3 = go.Figure(go.Bar(
            x=earn_counts.index.tolist(), y=earn_counts.values.tolist(),
            marker_color=earn_colors,
            text=earn_counts.values.tolist(), textposition='outside', textfont_color='white',
        ))
        fig3.update_layout(
            paper_bgcolor=DARK, plot_bgcolor='#161B22', height=220,
            margin=dict(t=30, b=10, l=10, r=10),
            title=dict(text='Earnings Status', font=dict(color=GRAY, size=12)),
            xaxis=dict(color=GRAY), yaxis=dict(color=GRAY, gridcolor='#222'),
            font=dict(color='white', family='Courier New'), showlegend=False,
        )
        st.plotly_chart(fig3, use_container_width=True)
