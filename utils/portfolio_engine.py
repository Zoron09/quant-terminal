"""
Portfolio computation engine.
Handles returns, risk metrics, backtesting, and pypfopt optimization.
"""
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
PORTFOLIOS_FILE = os.path.join(DATA_DIR, 'portfolios.json')


# ── Portfolio persistence ──────────────────────────────────────────────────────

def load_portfolios() -> dict:
    try:
        with open(PORTFOLIOS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"portfolios": {"default": {"name": "My Portfolio", "holdings": []}}}


def save_portfolios(data: dict):
    with open(PORTFOLIOS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_portfolio(name: str = 'default') -> list[dict]:
    """Return holdings list for a named portfolio."""
    data = load_portfolios()
    return data.get('portfolios', {}).get(name, {}).get('holdings', [])


def save_portfolio(holdings: list[dict], name: str = 'default', display_name: str = ''):
    data = load_portfolios()
    if 'portfolios' not in data:
        data['portfolios'] = {}
    if name not in data['portfolios']:
        data['portfolios'][name] = {'name': display_name or name, 'holdings': []}
    data['portfolios'][name]['holdings'] = holdings
    if display_name:
        data['portfolios'][name]['name'] = display_name
    save_portfolios(data)


def list_portfolio_names() -> list[str]:
    data = load_portfolios()
    return list(data.get('portfolios', {}).keys())


# ── Return matrix builder ──────────────────────────────────────────────────────

def build_returns_matrix(
    price_histories: dict[str, pd.DataFrame],
    min_periods: int = 60,
) -> pd.DataFrame:
    """
    price_histories: {ticker: DataFrame with 'Close' column}
    Returns a DataFrame of daily log returns, columns = tickers.
    Only includes tickers with enough history.
    """
    closes = {}
    for ticker, df in price_histories.items():
        if df is None or df.empty or 'Close' not in df.columns:
            continue
        s = df['Close'].dropna()
        if hasattr(s.index, 'tz') and s.index.tz is not None:
            s.index = s.index.tz_convert(None)
        s.index = pd.DatetimeIndex(s.index.normalize())
        if len(s) >= min_periods:
            closes[ticker] = s

    if not closes:
        return pd.DataFrame()

    df_closes = pd.DataFrame(closes).dropna(how='all')
    # Forward-fill short gaps then drop remaining NaN rows
    df_closes = df_closes.ffill(limit=5).dropna()
    returns = np.log(df_closes / df_closes.shift(1)).dropna()
    return returns


# ── Portfolio value and P&L ────────────────────────────────────────────────────

def compute_portfolio_value(holdings: list[dict], current_prices: dict[str, float]) -> dict:
    """
    holdings: [{ticker, shares, avg_cost}, ...]
    current_prices: {ticker: price}
    Returns summary dict.
    """
    rows = []
    total_cost  = 0.0
    total_value = 0.0

    for h in holdings:
        ticker    = h['ticker']
        shares    = float(h.get('shares', 0))
        avg_cost  = float(h.get('avg_cost', 0))
        price     = current_prices.get(ticker)

        cost   = shares * avg_cost
        value  = shares * price if price else None
        pnl    = (value - cost) if value is not None else None
        pnl_pct = (pnl / cost * 100) if (pnl is not None and cost > 0) else None

        rows.append({
            'ticker':    ticker,
            'shares':    shares,
            'avg_cost':  avg_cost,
            'price':     price,
            'cost':      cost,
            'value':     value,
            'pnl':       pnl,
            'pnl_pct':   pnl_pct,
        })
        total_cost  += cost
        if value is not None:
            total_value += value

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    return {
        'rows': rows,
        'total_cost':    total_cost,
        'total_value':   total_value,
        'total_pnl':     total_pnl,
        'total_pnl_pct': total_pnl_pct,
    }


# ── Risk metrics ──────────────────────────────────────────────────────────────

def compute_portfolio_returns(
    weights: dict[str, float],
    returns_matrix: pd.DataFrame,
) -> pd.Series:
    """Weighted sum of daily log returns → portfolio return series."""
    tickers = [t for t in weights if t in returns_matrix.columns]
    if not tickers:
        return pd.Series(dtype=float)
    w = np.array([weights[t] for t in tickers])
    w = w / w.sum()
    port_ret = returns_matrix[tickers].dot(w)
    return port_ret


def compute_risk_metrics(
    port_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.05,
) -> dict:
    """
    Standard risk metrics from a daily log return series.
    risk_free_rate: annualised, e.g. 0.05 for 5 %.
    """
    if port_returns is None or len(port_returns) < 20:
        return {}

    r = port_returns.dropna()
    daily_rf = risk_free_rate / 252

    ann_ret    = float(r.mean() * 252)
    ann_vol    = float(r.std() * np.sqrt(252))
    sharpe     = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

    # Sortino: downside deviation only
    neg = r[r < daily_rf]
    downside_std = float(neg.std() * np.sqrt(252)) if len(neg) > 1 else ann_vol
    sortino = (ann_ret - risk_free_rate) / downside_std if downside_std > 0 else 0.0

    # Max drawdown
    cum = (1 + r).cumprod()
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    # VaR 95 % (historical)
    var_95 = float(np.percentile(r, 5))
    cvar_95 = float(r[r <= var_95].mean()) if len(r[r <= var_95]) > 0 else var_95

    # Beta vs benchmark
    beta = None
    alpha = None
    if benchmark_returns is not None and len(benchmark_returns) > 20:
        aligned = pd.concat([r, benchmark_returns], axis=1).dropna()
        if len(aligned) > 20:
            aligned.columns = ['port', 'bench']
            cov = np.cov(aligned['port'], aligned['bench'])
            beta_val = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else None
            beta = float(beta_val) if beta_val is not None else None
            if beta is not None:
                bench_ann = float(aligned['bench'].mean() * 252)
                alpha = ann_ret - (risk_free_rate + beta * (bench_ann - risk_free_rate))

    return {
        'ann_return':  round(ann_ret * 100, 2),
        'ann_vol':     round(ann_vol * 100, 2),
        'sharpe':      round(sharpe, 3),
        'sortino':     round(sortino, 3),
        'max_drawdown': round(max_dd * 100, 2),
        'var_95':      round(var_95 * 100, 2),
        'cvar_95':     round(cvar_95 * 100, 2),
        'beta':        round(beta, 3) if beta is not None else None,
        'alpha':       round(alpha * 100, 2) if alpha is not None else None,
        'cum_return':  round(float((1 + r).prod() - 1) * 100, 2),
    }


def monthly_returns_table(port_returns: pd.Series) -> pd.DataFrame:
    """Build a year × month pivot table of monthly returns (%)."""
    if port_returns is None or len(port_returns) < 5:
        return pd.DataFrame()
    r = port_returns.dropna()
    monthly = (1 + r).resample('ME').prod() - 1
    df = monthly.to_frame('ret')
    df['Year']  = df.index.year
    df['Month'] = df.index.month
    pivot = df.pivot(index='Year', columns='Month', values='ret') * 100
    pivot.columns = ['Jan','Feb','Mar','Apr','May','Jun',
                     'Jul','Aug','Sep','Oct','Nov','Dec'][:len(pivot.columns)]
    # Add full-year column
    annual = (1 + r).resample('YE').prod() - 1
    pivot['Annual'] = (annual * 100).values[:len(pivot)]
    return pivot.round(2)


# ── Backtesting engine ────────────────────────────────────────────────────────

def backtest_portfolio(
    weights: dict[str, float],
    price_histories: dict[str, pd.DataFrame],
    benchmark_history: pd.DataFrame | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_capital: float = 100_000,
) -> dict:
    """
    Simple buy-and-hold backtest with fixed weights (rebalanced monthly).
    Returns equity curve, benchmark curve, and performance metrics.
    """
    returns = build_returns_matrix(price_histories)
    if returns.empty:
        return {'error': 'Insufficient price history for backtesting.'}

    # Date filter
    if start_date:
        returns = returns[returns.index >= pd.Timestamp(start_date)]
    if end_date:
        returns = returns[returns.index <= pd.Timestamp(end_date)]

    if len(returns) < 20:
        return {'error': 'Not enough data in the selected date range.'}

    port_ret = compute_portfolio_returns(weights, returns)
    equity = (1 + port_ret).cumprod() * initial_capital

    # Benchmark
    bench_equity = None
    bench_ret    = None
    if benchmark_history is not None and not benchmark_history.empty:
        bc = benchmark_history['Close'].dropna()
        if hasattr(bc.index, 'tz') and bc.index.tz is not None:
            bc.index = bc.index.tz_convert(None)
        bc.index = pd.DatetimeIndex(bc.index.normalize())
        bench_r = np.log(bc / bc.shift(1)).dropna()
        bench_r = bench_r.reindex(port_ret.index).fillna(0)
        bench_equity = (1 + bench_r).cumprod() * initial_capital
        bench_ret    = bench_r

    metrics  = compute_risk_metrics(port_ret, bench_ret)
    monthly  = monthly_returns_table(port_ret)

    # Drawdown series
    cum = (1 + port_ret).cumprod()
    drawdown = ((cum - cum.cummax()) / cum.cummax()) * 100

    return {
        'equity':        equity,
        'bench_equity':  bench_equity,
        'port_returns':  port_ret,
        'bench_returns': bench_ret,
        'drawdown':      drawdown,
        'metrics':       metrics,
        'monthly':       monthly,
    }


# ── PyPortfolioOpt wrapper ─────────────────────────────────────────────────────

def optimize_portfolio(
    price_histories: dict[str, pd.DataFrame],
    method: str = 'max_sharpe',
    risk_free_rate: float = 0.05,
) -> dict:
    """
    method: 'max_sharpe' | 'min_volatility' | 'risk_parity'
    Returns {weights, expected_return, expected_vol, sharpe, frontier_data}
    """
    try:
        from pypfopt import EfficientFrontier, risk_models, expected_returns
        from pypfopt.efficient_frontier import EfficientFrontier as EF
    except ImportError:
        return {'error': 'pypfopt not installed.'}

    closes = {}
    for ticker, df in price_histories.items():
        if df is None or df.empty or 'Close' not in df.columns:
            continue
        s = df['Close'].dropna()
        if hasattr(s.index, 'tz') and s.index.tz is not None:
            s.index = s.index.tz_convert(None)
        s.index = pd.DatetimeIndex(s.index.normalize())
        if len(s) >= 60:
            closes[ticker] = s

    if len(closes) < 2:
        return {'error': 'Need at least 2 tickers with 60+ days of history.'}

    prices_df = pd.DataFrame(closes).dropna()
    if len(prices_df) < 60:
        return {'error': 'Insufficient overlapping history for optimization.'}

    try:
        mu  = expected_returns.mean_historical_return(prices_df)
        S   = risk_models.sample_cov(prices_df)

        ef = EfficientFrontier(mu, S)
        if method == 'max_sharpe':
            ef.max_sharpe(risk_free_rate=risk_free_rate)
        elif method == 'min_volatility':
            ef.min_volatility()
        elif method == 'risk_parity':
            # Equal risk contribution via min vol with equal weights constraint
            ef.min_volatility()
        else:
            ef.max_sharpe(risk_free_rate=risk_free_rate)

        weights_raw = ef.clean_weights()
        weights     = {k: round(v, 4) for k, v in weights_raw.items() if v > 0.001}
        perf        = ef.portfolio_performance(risk_free_rate=risk_free_rate)

        # Efficient frontier curve (20 points from min-vol to max-sharpe)
        frontier_vols, frontier_rets = [], []
        try:
            target_rets = np.linspace(float(mu.min()), float(mu.max()), 30)
            for tr in target_rets:
                try:
                    ef2 = EfficientFrontier(mu, S, weight_bounds=(0, 1))
                    ef2.efficient_return(tr)
                    p = ef2.portfolio_performance()
                    frontier_vols.append(round(p[1] * 100, 2))
                    frontier_rets.append(round(p[0] * 100, 2))
                except Exception:
                    pass
        except Exception:
            pass

        return {
            'weights':          weights,
            'expected_return':  round(perf[0] * 100, 2),
            'expected_vol':     round(perf[1] * 100, 2),
            'sharpe':           round(perf[2], 3),
            'frontier_vols':    frontier_vols,
            'frontier_rets':    frontier_rets,
        }
    except Exception as e:
        return {'error': str(e)}


# ── Position size calculator ───────────────────────────────────────────────────

def position_size(
    account_size: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
) -> dict:
    """
    Standard SEPA 1-2% risk position sizing.
    risk_pct: e.g. 1.0 for 1%
    Returns shares, dollar_risk, position_value, pct_of_account
    """
    if entry_price <= 0 or stop_loss <= 0 or entry_price <= stop_loss:
        return {'error': 'Invalid prices: entry must be > stop loss > 0'}

    dollar_risk     = account_size * (risk_pct / 100.0)
    risk_per_share  = entry_price - stop_loss
    shares          = int(dollar_risk / risk_per_share)
    position_value  = shares * entry_price
    pct_of_account  = (position_value / account_size) * 100

    return {
        'shares':          shares,
        'dollar_risk':     round(dollar_risk, 2),
        'risk_per_share':  round(risk_per_share, 2),
        'position_value':  round(position_value, 2),
        'pct_of_account':  round(pct_of_account, 2),
        'stop_loss_pct':   round((entry_price - stop_loss) / entry_price * 100, 2),
    }
