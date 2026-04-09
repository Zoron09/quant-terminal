import streamlit as st
import sys, os
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sidebar import render_sidebar
from utils.portfolio_engine import (
    load_portfolios, save_portfolio, list_portfolio_names, get_portfolio,
    compute_portfolio_value, build_returns_matrix, compute_portfolio_returns,
    compute_risk_metrics, monthly_returns_table, backtest_portfolio,
    optimize_portfolio, position_size,
)
from utils.formatters import fmt_large_number, fmt_pct, fmt_price

st.set_page_config(page_title="Portfolio · Quant Terminal", page_icon="💼", layout="wide")

_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')
if os.path.exists(_css):
    with open(_css) as _f:
        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)

render_sidebar()

DARK = dict(
    plot_bgcolor='#0E1117', paper_bgcolor='#0E1117',
    font=dict(color='#CCCCCC', family='Courier New'),
)

st.markdown("## 💼 Portfolio Manager")

# ── Portfolio selector ────────────────────────────────────────────────────────
port_names = list_portfolio_names()
if not port_names:
    port_names = ['default']

sel_col, new_col = st.columns([3, 2])
with sel_col:
    active_port = st.selectbox("Portfolio", port_names, key="active_portfolio")
with new_col:
    with st.popover("+ New Portfolio"):
        new_name = st.text_input("Name (no spaces)", key="new_port_name")
        if st.button("Create", key="btn_create_port"):
            if new_name and new_name not in port_names:
                save_portfolio([], name=new_name.lower(), display_name=new_name)
                st.success(f"Created: {new_name}")
                st.rerun()

holdings = get_portfolio(active_port)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_hold, tab_opt, tab_risk, tab_back, tab_pos = st.tabs([
    "Holdings", "Optimizer", "Risk Metrics", "Backtest", "Position Sizer"
])


# ════════════════════════════════════════════════════════════════════════════
# HELPER — fetch prices for all holdings
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _get_cad_usd() -> float:
    """Return CAD/USD exchange rate via yfinance, fallback to 0.74."""
    try:
        import yfinance as yf
        fi = yf.Ticker('CADUSD=X').fast_info
        p  = fi.get('lastPrice') or fi.get('regularMarketPrice')
        if p:
            return float(p)
    except Exception:
        pass
    return 0.74  # reasonable fallback


@st.cache_data(ttl=300, show_spinner=False)
def _get_current_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """Fetch latest prices for a set of tickers.
    US tickers use Alpaca (real-time incl. pre/post market), then yfinance.
    Canadian .TO tickers use yfinance; prices returned in CAD.
    """
    prices = {}

    # Separate US and non-US tickers
    us_tickers     = [t for t in tickers if '.' not in t]
    non_us_tickers = [t for t in tickers if '.' in t]

    # Alpaca for US tickers (real-time, incl. extended hours)
    if us_tickers:
        try:
            from utils.alpaca_client import get_snapshots, _HAS_ALPACA
            if _HAS_ALPACA:
                snaps = get_snapshots(tuple(us_tickers))
                for sym, d in snaps.items():
                    if d.get('price'):
                        prices[sym] = d['price']
        except Exception:
            pass

    # yfinance for everything missing (non-US and Alpaca misses)
    missing = [t for t in tickers if t not in prices]
    if missing:
        try:
            import yfinance as yf
            for t in missing:
                try:
                    fi = yf.Ticker(t).fast_info
                    p  = fi.get('lastPrice') or fi.get('regularMarketPrice')
                    if p:
                        prices[t] = float(p)
                except Exception:
                    pass
        except Exception:
            pass

    return prices


@st.cache_data(ttl=900, show_spinner=False)
def _get_history(tickers: tuple[str, ...], years: int = 3) -> dict[str, pd.DataFrame]:
    """Fetch price history for a set of tickers."""
    histories = {}
    for t in tickers:
        try:
            from utils.data_fetcher import get_price_history
            df = get_price_history(t, period=f"{years}y")
            if df is not None and not df.empty:
                histories[t] = df
        except Exception:
            pass
    return histories


# ════════════════════════════════════════════════════════════════════════════
# TAB 1: HOLDINGS
# ════════════════════════════════════════════════════════════════════════════
with tab_hold:
    st.markdown('<div class="section-title">Holdings</div>', unsafe_allow_html=True)

    # ── Add single holding with validation ───────────────────────────────
    with st.expander("Add Holding", expanded=not bool(holdings)):
        st.caption("Supports US (AAPL), Indian (.NS/.BO), and Canadian (.TO) stocks.")
        ah1, ah2, ah3, ah4 = st.columns([2, 1, 2, 1])
        with ah1:
            new_ticker = st.text_input("Ticker", placeholder="e.g. AAPL, RELIANCE.NS, XDIV.TO",
                                       key="new_hold_ticker").strip().upper()
        with ah2:
            new_shares = st.number_input("Shares", min_value=0.0001, value=1.0,
                                         format="%.4f", key="new_hold_shares")
        with ah3:
            new_cost = st.number_input("Avg Cost", min_value=0.01, value=100.0,
                                       format="%.2f", key="new_hold_cost")
        with ah4:
            st.markdown("<br>", unsafe_allow_html=True)
            add_btn = st.button("Add", key="btn_add_hold", use_container_width=True)

        if add_btn and new_ticker:
            # Validate ticker via yfinance
            try:
                import yfinance as yf
                test_fi = yf.Ticker(new_ticker).fast_info
                test_p  = test_fi.get('lastPrice') or test_fi.get('regularMarketPrice')
                if not test_p:
                    raise ValueError("No price returned")
                # Normalise VISA→V common mistake
                ticker_map = {'VISA': 'V', 'MASTERCARD': 'MA', 'GOOGLE': 'GOOGL',
                              'FACEBOOK': 'META', 'TWITTER': 'X'}
                if new_ticker in ticker_map:
                    st.warning(f"Did you mean {ticker_map[new_ticker]}? Auto-corrected.")
                    new_ticker = ticker_map[new_ticker]
                new_h = {'ticker': new_ticker, 'shares': float(new_shares), 'avg_cost': float(new_cost)}
                holdings = [h for h in holdings if h['ticker'].upper() != new_ticker]
                holdings.append(new_h)
                save_portfolio(holdings, name=active_port)
                st.success(f"Added {new_ticker} — {new_shares:.4f} shares @ ${new_cost:.2f}")
                st.rerun()
            except Exception:
                st.error(f"Could not validate ticker '{new_ticker}'. Check the symbol and try again.")

    # ── Quick delete per holding ──────────────────────────────────────────
    if holdings:
        st.markdown("**Remove a holding:**")
        del_cols = st.columns(min(len(holdings), 6))
        for idx, h in enumerate(holdings):
            col = del_cols[idx % len(del_cols)]
            if col.button(f"✕ {h['ticker']}", key=f"del_hold_{idx}_{h['ticker']}"):
                holdings = [x for x in holdings if x['ticker'] != h['ticker']]
                save_portfolio(holdings, name=active_port)
                st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Edit all holdings via data_editor ─────────────────────────────────
    with st.expander("Edit All Holdings", expanded=False):
        st.caption("Edit existing holdings. Use the Add form above for new positions.")
        existing_df = pd.DataFrame(holdings) if holdings else pd.DataFrame(
            columns=['ticker', 'shares', 'avg_cost']
        )
        if existing_df.empty or 'ticker' not in existing_df.columns:
            existing_df = pd.DataFrame([{'ticker': '', 'shares': 0.0, 'avg_cost': 0.0}])

        edited = st.data_editor(
            existing_df[['ticker', 'shares', 'avg_cost']],
            num_rows="dynamic",
            column_config={
                'ticker':   st.column_config.TextColumn("Ticker", width="small"),
                'shares':   st.column_config.NumberColumn("Shares", min_value=0, format="%.4f"),
                'avg_cost': st.column_config.NumberColumn("Avg Cost ($)", min_value=0, format="%.2f"),
            },
            use_container_width=True,
            key="holdings_editor",
        )

        if st.button("Save Changes", key="btn_save_holdings"):
            new_holdings = []
            for _, row in edited.iterrows():
                t = str(row.get('ticker', '') or '').strip().upper()
                s = float(row.get('shares', 0) or 0)
                c = float(row.get('avg_cost', 0) or 0)
                if t and s > 0:
                    new_holdings.append({'ticker': t, 'shares': s, 'avg_cost': c})
            save_portfolio(new_holdings, name=active_port)
            holdings = new_holdings
            st.success(f"Saved {len(new_holdings)} holding(s).")
            st.rerun()

    if not holdings:
        st.info("No holdings yet. Add some above.")
        st.stop()

    # ── Fetch live prices ─────────────────────────────────────────────────
    tickers_tuple = tuple(h['ticker'].upper() for h in holdings)
    has_canadian  = any(t.endswith('.TO') for t in tickers_tuple)
    with st.spinner("Fetching current prices…"):
        prices = _get_current_prices(tickers_tuple)
        if has_canadian:
            cad_usd = _get_cad_usd()
            # Convert .TO prices from CAD to USD for portfolio totals
            prices_usd = {}
            for t, p in prices.items():
                prices_usd[t] = p * cad_usd if t.endswith('.TO') else p
        else:
            prices_usd = prices

    pv = compute_portfolio_value(holdings, prices_usd)

    # ── Summary cards ─────────────────────────────────────────────────────
    sc1, sc2, sc3, sc4 = st.columns(4)
    def _stat_card(col, label, value, color='#CCCCCC', sub=''):
        col.markdown(f"""
<div class="stat-card" style="border-left-color:{color};">
  <div class="stat-label">{label}</div>
  <div class="stat-value" style="color:{color}">{value}</div>
  {'<div style="color:#888;font-size:11px;">' + sub + '</div>' if sub else ''}
</div>""", unsafe_allow_html=True)

    pnl_color = '#00FF41' if pv['total_pnl'] >= 0 else '#FF4444'
    _stat_card(sc1, "Portfolio Value",  fmt_large_number(pv['total_value']), '#00BFFF')
    _stat_card(sc2, "Total Cost",       fmt_large_number(pv['total_cost']),  '#888888')
    _stat_card(sc3, "Total P&L",
               f"{'+' if pv['total_pnl']>=0 else ''}{fmt_large_number(pv['total_pnl'])}",
               pnl_color, f"{pv['total_pnl_pct']:+.2f}%")
    _stat_card(sc4, "Positions", str(len(holdings)), '#FFD700')

    st.markdown("---")

    # ── Holdings table ────────────────────────────────────────────────────
    rows_html = ''
    for row in pv['rows']:
        p   = row['price']
        pnl = row['pnl']
        pct = row['pnl_pct']
        p_color   = '#CCCCCC'
        pnl_color = '#888888' if pnl is None else ('#00FF41' if pnl >= 0 else '#FF4444')
        p_str     = f"${p:,.2f}"    if p   is not None else 'N/A'
        val_str   = fmt_large_number(row['value'])
        pnl_str   = (f"{'+' if pnl >= 0 else ''}{fmt_large_number(pnl)}" if pnl is not None else 'N/A')
        pct_str   = (f"{pct:+.2f}%" if pct is not None else 'N/A')
        rows_html += f"""<tr>
  <td style="font-family:monospace;color:#00BFFF;font-weight:bold">{row['ticker']}</td>
  <td style="text-align:right;font-family:monospace">{row['shares']:,.4f}</td>
  <td style="text-align:right;font-family:monospace">${row['avg_cost']:,.2f}</td>
  <td style="text-align:right;font-family:monospace;color:{p_color}">{p_str}</td>
  <td style="text-align:right;font-family:monospace">{fmt_large_number(row['cost'])}</td>
  <td style="text-align:right;font-family:monospace">{val_str}</td>
  <td style="text-align:right;font-family:monospace;color:{pnl_color}">{pnl_str}</td>
  <td style="text-align:right;font-family:monospace;color:{pnl_color}">{pct_str}</td>
</tr>"""

    table_html = f"""
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead><tr style="background:#161B22;color:#888;text-transform:uppercase;font-size:10px;
                  border-bottom:1px solid #333;letter-spacing:1px;font-family:monospace;">
  <th style="padding:7px 8px;text-align:left;">Ticker</th>
  <th style="padding:7px 8px;text-align:right;">Shares</th>
  <th style="padding:7px 8px;text-align:right;">Avg Cost</th>
  <th style="padding:7px 8px;text-align:right;">Price</th>
  <th style="padding:7px 8px;text-align:right;">Cost Basis</th>
  <th style="padding:7px 8px;text-align:right;">Market Value</th>
  <th style="padding:7px 8px;text-align:right;">P&L</th>
  <th style="padding:7px 8px;text-align:right;">P&L %</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table></div>"""
    st.markdown(table_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Allocation charts ─────────────────────────────────────────────────
    ch1, ch2 = st.columns(2)

    valued_rows = [r for r in pv['rows'] if r['value'] is not None]
    if valued_rows:
        labels = [r['ticker'] for r in valued_rows]
        vals   = [r['value'] for r in valued_rows]

        with ch1:
            fig_alloc = go.Figure(go.Pie(
                labels=labels, values=vals,
                hole=0.55,
                textinfo='label+percent',
                marker=dict(colors=px.colors.qualitative.Bold),
            ))
            fig_alloc.update_layout(
                **DARK, height=300,
                title=dict(text='Allocation by Holding', font=dict(color='#CCCCCC', size=13)),
                margin=dict(l=0, r=0, t=40, b=0), showlegend=False,
            )
            st.plotly_chart(fig_alloc, use_container_width=True)

        # Sector allocation (best-effort via yfinance)
        with ch2:
            sector_map = {}
            try:
                import yfinance as yf
                for r in valued_rows:
                    try:
                        info   = yf.Ticker(r['ticker']).info
                        sector = info.get('sector', 'Unknown') or 'Unknown'
                        sector_map[r['ticker']] = sector
                    except Exception:
                        sector_map[r['ticker']] = 'Unknown'
            except Exception:
                sector_map = {r['ticker']: 'Unknown' for r in valued_rows}

            sector_vals = {}
            for r in valued_rows:
                sec = sector_map.get(r['ticker'], 'Unknown')
                sector_vals[sec] = sector_vals.get(sec, 0) + (r['value'] or 0)

            if sector_vals:
                fig_sec = go.Figure(go.Pie(
                    labels=list(sector_vals.keys()),
                    values=list(sector_vals.values()),
                    hole=0.55, textinfo='label+percent',
                    marker=dict(colors=px.colors.qualitative.Pastel),
                ))
                fig_sec.update_layout(
                    **DARK, height=300,
                    title=dict(text='Sector Allocation', font=dict(color='#CCCCCC', size=13)),
                    margin=dict(l=0, r=0, t=40, b=0), showlegend=False,
                )
                st.plotly_chart(fig_sec, use_container_width=True)

    if has_canadian:
        st.caption(f"Prices refreshed every 5 min · .TO holdings converted CAD→USD @ {cad_usd:.4f} · Sector data from yfinance")
    else:
        st.caption("Prices refreshed every 5 min · US prices via Alpaca (real-time incl. extended hours) · Sector data from yfinance")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2: OPTIMIZER
# ════════════════════════════════════════════════════════════════════════════
with tab_opt:
    st.markdown('<div class="section-title">Portfolio Optimizer</div>', unsafe_allow_html=True)

    if not holdings:
        st.info("Add holdings first.")
    else:
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            opt_method = st.selectbox(
                "Optimization Method",
                ["max_sharpe", "min_volatility", "risk_parity"],
                format_func=lambda x: {
                    'max_sharpe': 'Max Sharpe Ratio',
                    'min_volatility': 'Min Volatility',
                    'risk_parity': 'Risk Parity',
                }[x],
                key="opt_method",
            )
        with oc2:
            rf_rate = st.number_input("Risk-Free Rate (%)", value=5.0, min_value=0.0,
                                      max_value=20.0, step=0.1, key="opt_rf") / 100
        with oc3:
            opt_years = st.selectbox("History", [1, 2, 3, 5], index=1,
                                     format_func=lambda x: f"{x} year{'s' if x>1 else ''}",
                                     key="opt_years")

        if st.button("Run Optimizer", key="btn_run_opt"):
            tickers_tuple_opt = tuple(h['ticker'].upper() for h in holdings)
            with st.spinner("Fetching price history and optimizing…"):
                histories = _get_history(tickers_tuple_opt, years=opt_years)
                result    = optimize_portfolio(histories, method=opt_method, risk_free_rate=rf_rate)

            if 'error' in result:
                st.error(result['error'])
            else:
                weights  = result['weights']
                exp_ret  = result['expected_return']
                exp_vol  = result['expected_vol']
                sharpe   = result['sharpe']
                fr_vols  = result['frontier_vols']
                fr_rets  = result['frontier_rets']

                # Performance summary
                pc1, pc2, pc3 = st.columns(3)
                _stat_card(pc1, "Expected Return", f"{exp_ret:.2f}%", '#00FF41')
                _stat_card(pc2, "Expected Volatility", f"{exp_vol:.2f}%", '#FFD700')
                _stat_card(pc3, "Sharpe Ratio", f"{sharpe:.3f}", '#00BFFF')

                st.markdown("<br>", unsafe_allow_html=True)

                # Weights comparison
                wc1, wc2 = st.columns(2)

                with wc1:
                    st.markdown("**Optimal Weights**")
                    # Current equal-weight
                    eq_w = 1 / len(holdings)
                    for t in sorted(weights, key=lambda x: -weights[x]):
                        w   = weights[t]
                        cur = eq_w
                        # Try to get actual current weight
                        total_val = pv.get('total_value', 0) if 'pv' in dir() else 0
                        if total_val > 0:
                            for r in pv['rows']:
                                if r['ticker'] == t and r['value']:
                                    cur = r['value'] / total_val
                                    break
                        bar_w = int(w * 200)
                        st.markdown(f"""
<div style="margin-bottom:6px;">
  <span style="font-family:monospace;color:#00BFFF;min-width:60px;display:inline-block;">{t}</span>
  <span style="display:inline-block;background:#00FF41;height:12px;width:{bar_w}px;
               vertical-align:middle;border-radius:2px;margin:0 8px;"></span>
  <span style="font-family:monospace;color:#00FF41;">{w*100:.1f}%</span>
  <span style="color:#555;font-size:10px;margin-left:8px;">(current: {cur*100:.1f}%)</span>
</div>""", unsafe_allow_html=True)

                with wc2:
                    if fr_vols and fr_rets:
                        fig_ef = go.Figure()
                        fig_ef.add_trace(go.Scatter(
                            x=fr_vols, y=fr_rets,
                            mode='lines', line=dict(color='#00BFFF', width=2),
                            name='Efficient Frontier',
                        ))
                        fig_ef.add_trace(go.Scatter(
                            x=[exp_vol], y=[exp_ret],
                            mode='markers',
                            marker=dict(color='#00FF41', size=12, symbol='star'),
                            name='Optimal Portfolio',
                        ))
                        fig_ef.update_layout(
                            **DARK, height=300,
                            title='Efficient Frontier',
                            xaxis_title='Volatility (%)',
                            yaxis_title='Expected Return (%)',
                            margin=dict(l=40, r=20, t=40, b=40),
                        )
                        st.plotly_chart(fig_ef, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: RISK METRICS
# ════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown('<div class="section-title">Risk Metrics</div>', unsafe_allow_html=True)

    if not holdings:
        st.info("Add holdings first.")
    else:
        rc1, rc2 = st.columns([2, 1])
        with rc1:
            risk_years = st.selectbox("History", [1, 2, 3, 5], index=1,
                                      format_func=lambda x: f"{x} year{'s' if x>1 else ''}",
                                      key="risk_years")
        with rc2:
            rf_risk = st.number_input("Risk-Free Rate (%)", value=5.0,
                                      min_value=0.0, max_value=20.0, step=0.1,
                                      key="rf_risk") / 100

        if st.button("Compute Risk Metrics", key="btn_risk"):
            tickers_tuple_r = tuple(h['ticker'].upper() for h in holdings)
            with st.spinner("Fetching history…"):
                histories_r = _get_history(tickers_tuple_r, years=risk_years)
                # Benchmark: SPY
                from utils.data_fetcher import get_price_history
                spy_df = get_price_history('SPY', period=f"{risk_years}y")

            # Current weights from portfolio value
            weights_r = {}
            total_v = sum(
                (h['shares'] * prices.get(h['ticker'], h['avg_cost']))
                for h in holdings
            )
            for h in holdings:
                p = prices.get(h['ticker'], h['avg_cost'])
                v = h['shares'] * p
                weights_r[h['ticker']] = v / total_v if total_v > 0 else 1 / len(holdings)

            returns_r = build_returns_matrix(histories_r)
            if returns_r.empty:
                st.error("Insufficient price history.")
            else:
                port_ret_r = compute_portfolio_returns(weights_r, returns_r)

                bench_ret_r = None
                if spy_df is not None and not spy_df.empty:
                    sc = spy_df['Close'].dropna()
                    if hasattr(sc.index, 'tz') and sc.index.tz is not None:
                        sc.index = sc.index.tz_convert(None)
                    sc.index = pd.DatetimeIndex(sc.index.normalize())
                    bench_ret_r = np.log(sc / sc.shift(1)).dropna()
                    bench_ret_r = bench_ret_r.reindex(port_ret_r.index).fillna(0)

                metrics_r = compute_risk_metrics(port_ret_r, bench_ret_r, rf_risk)

                # Metrics grid
                mets = [
                    ("Ann. Return",      f"{metrics_r.get('ann_return',0):+.2f}%",  '#00FF41' if metrics_r.get('ann_return',0) >= 0 else '#FF4444'),
                    ("Ann. Volatility",  f"{metrics_r.get('ann_vol',0):.2f}%",      '#FFD700'),
                    ("Sharpe Ratio",     f"{metrics_r.get('sharpe',0):.3f}",         '#00BFFF'),
                    ("Sortino Ratio",    f"{metrics_r.get('sortino',0):.3f}",        '#00BFFF'),
                    ("Max Drawdown",     f"{metrics_r.get('max_drawdown',0):.2f}%",  '#FF4444'),
                    ("VaR 95%",          f"{metrics_r.get('var_95',0):.2f}%",        '#FF4444'),
                    ("CVaR 95%",         f"{metrics_r.get('cvar_95',0):.2f}%",       '#FF4444'),
                    ("Beta (vs SPY)",    str(metrics_r.get('beta','N/A') or 'N/A'),  '#888888'),
                    ("Alpha (ann.)",     f"{metrics_r.get('alpha',0) or 0:+.2f}%",  '#00FF41' if (metrics_r.get('alpha') or 0) >= 0 else '#FF4444'),
                    ("Cumulative Ret.",  f"{metrics_r.get('cum_return',0):+.2f}%",   '#00FF41' if metrics_r.get('cum_return',0) >= 0 else '#FF4444'),
                ]
                cols_m = st.columns(5)
                for idx, (lbl, val, col) in enumerate(mets):
                    _stat_card(cols_m[idx % 5], lbl, val, col)

                st.markdown("---")

                # Correlation matrix
                if len(returns_r.columns) > 1:
                    st.markdown("**Correlation Matrix**")
                    corr = returns_r.corr()
                    fig_corr = go.Figure(go.Heatmap(
                        z=corr.values,
                        x=corr.columns.tolist(),
                        y=corr.index.tolist(),
                        colorscale=[[0, '#FF4444'], [0.5, '#0E1117'], [1, '#00FF41']],
                        zmin=-1, zmax=1,
                        text=[[f"{v:.2f}" for v in row] for row in corr.values],
                        texttemplate="%{text}",
                        colorbar=dict(tickfont=dict(color='#CCCCCC')),
                    ))
                    fig_corr.update_layout(
                        **DARK, height=400,
                        title='Return Correlations',
                        margin=dict(l=60, r=20, t=40, b=60),
                        xaxis=dict(tickfont=dict(color='#CCCCCC')),
                        yaxis=dict(tickfont=dict(color='#CCCCCC')),
                    )
                    st.plotly_chart(fig_corr, use_container_width=True)

                # Monthly returns heatmap
                monthly_r = monthly_returns_table(port_ret_r)
                if not monthly_r.empty:
                    st.markdown("**Monthly Returns (%)**")
                    # Color-code the values
                    styled = monthly_r.style.background_gradient(
                        cmap='RdYlGn', vmin=-10, vmax=10
                    ).format("{:.2f}%", na_rep="—")
                    st.dataframe(styled, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 4: BACKTEST
# ════════════════════════════════════════════════════════════════════════════
with tab_back:
    st.markdown('<div class="section-title">Backtesting</div>', unsafe_allow_html=True)

    if not holdings:
        st.info("Add holdings first.")
    else:
        bc1, bc2, bc3, bc4 = st.columns(4)
        with bc1:
            bt_start = st.date_input("Start Date",
                                     value=datetime.now() - timedelta(days=3*365),
                                     key="bt_start")
        with bc2:
            bt_end = st.date_input("End Date", value=datetime.now(), key="bt_end")
        with bc3:
            bt_capital = st.number_input("Initial Capital ($)", value=100_000,
                                         min_value=1_000, step=10_000, key="bt_capital")
        with bc4:
            bt_weight_mode = st.selectbox("Weighting", ["equal", "value"], key="bt_weight_mode")

        if st.button("Run Backtest", key="btn_backtest"):
            tickers_bt = tuple(h['ticker'].upper() for h in holdings)
            with st.spinner("Fetching data and running backtest…"):
                # Fetch enough history
                years_needed = max(1, (datetime.now() - datetime.combine(bt_start, datetime.min.time())).days // 365 + 1)
                histories_bt = _get_history(tickers_bt, years=years_needed + 1)
                from utils.data_fetcher import get_price_history
                spy_bt = get_price_history('SPY', period=f"{years_needed + 1}y")

            # Weights
            if bt_weight_mode == 'equal':
                weights_bt = {h['ticker'].upper(): 1.0 / len(holdings) for h in holdings}
            else:
                total_cost_bt = sum(h['shares'] * h['avg_cost'] for h in holdings)
                weights_bt = {
                    h['ticker'].upper(): (h['shares'] * h['avg_cost']) / total_cost_bt
                    for h in holdings
                } if total_cost_bt > 0 else {h['ticker'].upper(): 1.0/len(holdings) for h in holdings}

            result_bt = backtest_portfolio(
                weights=weights_bt,
                price_histories=histories_bt,
                benchmark_history=spy_bt,
                start_date=str(bt_start),
                end_date=str(bt_end),
                initial_capital=bt_capital,
            )

            if 'error' in result_bt:
                st.error(result_bt['error'])
            else:
                equity    = result_bt['equity']
                bench_eq  = result_bt['bench_equity']
                drawdown  = result_bt['drawdown']
                metrics_bt = result_bt['metrics']
                monthly_bt = result_bt['monthly']

                # Performance summary
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                _stat_card(mc1, "Total Return",  f"{metrics_bt.get('cum_return',0):+.2f}%",
                           '#00FF41' if metrics_bt.get('cum_return',0) >= 0 else '#FF4444')
                _stat_card(mc2, "Ann. Return",   f"{metrics_bt.get('ann_return',0):+.2f}%",
                           '#00FF41' if metrics_bt.get('ann_return',0) >= 0 else '#FF4444')
                _stat_card(mc3, "Sharpe",        f"{metrics_bt.get('sharpe',0):.3f}", '#00BFFF')
                _stat_card(mc4, "Max Drawdown",  f"{metrics_bt.get('max_drawdown',0):.2f}%", '#FF4444')
                _stat_card(mc5, "Ann. Vol",      f"{metrics_bt.get('ann_vol',0):.2f}%", '#FFD700')

                st.markdown("<br>", unsafe_allow_html=True)

                # Equity curve
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=equity.index, y=equity.values,
                    mode='lines', line=dict(color='#00FF41', width=2),
                    name='Portfolio',
                    hovertemplate='%{x|%Y-%m-%d}: $%{y:,.0f}',
                ))
                if bench_eq is not None:
                    fig_eq.add_trace(go.Scatter(
                        x=bench_eq.index, y=bench_eq.values,
                        mode='lines', line=dict(color='#888888', width=1.5, dash='dot'),
                        name='SPY Benchmark',
                        hovertemplate='%{x|%Y-%m-%d}: $%{y:,.0f}',
                    ))
                fig_eq.update_layout(
                    **DARK, height=350,
                    title='Equity Curve',
                    yaxis_title='Portfolio Value ($)',
                    margin=dict(l=60, r=20, t=40, b=40),
                    legend=dict(font=dict(color='#CCCCCC')),
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                # Drawdown chart
                fig_dd = go.Figure(go.Scatter(
                    x=drawdown.index, y=drawdown.values,
                    mode='lines', fill='tozeroy',
                    line=dict(color='#FF4444', width=1),
                    fillcolor='rgba(255,68,68,0.15)',
                    hovertemplate='%{x|%Y-%m-%d}: %{y:.2f}%',
                ))
                fig_dd.update_layout(
                    **DARK, height=200,
                    title='Drawdown (%)',
                    yaxis_title='Drawdown (%)',
                    margin=dict(l=60, r=20, t=40, b=40),
                )
                st.plotly_chart(fig_dd, use_container_width=True)

                # Monthly returns
                if not monthly_bt.empty:
                    st.markdown("**Monthly Returns (%)**")
                    styled_bt = monthly_bt.style.background_gradient(
                        cmap='RdYlGn', vmin=-10, vmax=10
                    ).format("{:.2f}%", na_rep="—")
                    st.dataframe(styled_bt, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 5: POSITION SIZER
# ════════════════════════════════════════════════════════════════════════════
with tab_pos:
    st.markdown('<div class="section-title">Position Size Calculator</div>', unsafe_allow_html=True)
    st.caption("SEPA-style: risk a fixed % of account on each trade, defined by entry and stop-loss.")

    ps1, ps2 = st.columns(2)
    with ps1:
        ps_account = st.number_input("Account Size ($)", value=50_000.0,
                                     min_value=100.0, step=1_000.0, format="%.2f",
                                     key="ps_account")
        ps_risk_pct = st.slider("Risk per Trade (%)", 0.25, 5.0, 1.0, 0.25, key="ps_risk_pct")
        ps_entry    = st.number_input("Entry Price ($)", value=100.0,
                                      min_value=0.01, step=0.5, format="%.2f",
                                      key="ps_entry")
        ps_stop     = st.number_input("Stop Loss ($)", value=90.0,
                                      min_value=0.01, step=0.5, format="%.2f",
                                      key="ps_stop")

        calc = position_size(ps_account, ps_risk_pct, ps_entry, ps_stop)

        # 10% max stop-loss enforcement
        if 'stop_loss_pct' in calc and calc['stop_loss_pct'] > 10.0:
            st.warning(
                f"⚠ Stop-loss is {calc['stop_loss_pct']:.1f}% — exceeds 10% maximum. "
                "Minervini recommends ≤ 8% initial stop. Tighten your stop or raise your entry."
            )

    with ps2:
        if 'error' in calc:
            st.error(calc['error'])
        else:
            results = [
                ("Shares to Buy",        f"{calc['shares']:,}",                    '#00FF41'),
                ("Dollar Risk",          f"${calc['dollar_risk']:,.2f}",            '#FF4444'),
                ("Risk per Share",       f"${calc['risk_per_share']:.2f}",          '#FF4444'),
                ("Position Value",       f"${calc['position_value']:,.2f}",         '#00BFFF'),
                ("% of Account",         f"{calc['pct_of_account']:.2f}%",          '#FFD700'),
                ("Stop Loss Distance",   f"{calc['stop_loss_pct']:.2f}%",           '#888888'),
            ]
            for lbl, val, col in results:
                st.markdown(f"""
<div class="stat-card" style="border-left-color:{col};margin-bottom:8px;">
  <div class="stat-label">{lbl}</div>
  <div class="stat-value" style="color:{col}">{val}</div>
</div>""", unsafe_allow_html=True)

            # Reward/risk visual
            st.markdown("---")
            st.markdown("**Risk / Reward Ladder**")
            for rr, label in [(1.5, '1.5R'), (2.0, '2R'), (3.0, '3R'), (5.0, '5R')]:
                target = ps_entry + (ps_entry - ps_stop) * rr
                gain   = calc['shares'] * (target - ps_entry)
                st.markdown(
                    f"<span style='color:#888;font-family:monospace;font-size:12px;'>"
                    f"{label}: target ${target:.2f} → gain "
                    f"<span style='color:#00FF41'>${gain:,.0f}</span></span>",
                    unsafe_allow_html=True,
                )

    st.caption("Formula: Shares = (Account × Risk%) ÷ (Entry − Stop) · Max Minervini recommended: 1-2% risk")
