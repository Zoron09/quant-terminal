"""
SEPA / Minervini Trend Template engine.
All calculations use yfinance price history (daily OHLCV).
"""
import numpy as np
import pandas as pd
from typing import Optional


# ── helpers ──────────────────────────────────────────────────────────────────

def _sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=max(1, n // 2)).mean()


def _slope_positive(series: pd.Series, lookback: int = 20) -> bool:
    """True when the last `lookback` values have a positive linear slope."""
    if len(series) < lookback:
        return False
    y = series.dropna().tail(lookback).values
    if len(y) < 2:
        return False
    x = np.arange(len(y), dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    return float(slope) > 0


# ── Trend Template ────────────────────────────────────────────────────────────

def compute_trend_template(df: pd.DataFrame) -> dict:
    """
    Evaluate all 8 Minervini Trend Template criteria.

    Returns a dict with:
      criteria: list of {id, label, result, value, note}
      pass_count: int
      qualified: bool
    """
    if df is None or df.empty or len(df) < 200:
        return {'criteria': [], 'pass_count': 0, 'qualified': False,
                'error': 'Not enough price history (need 200+ trading days).'}

    close = df['Close'].dropna()
    price = float(close.iloc[-1])

    ma50  = float(_sma(close, 50).iloc[-1])
    ma150 = float(_sma(close, 150).iloc[-1])
    ma200 = float(_sma(close, 200).iloc[-1])

    hi52 = float(close.tail(252).max())
    lo52 = float(close.tail(252).min())

    ma200_series = _sma(close, 200)
    ma200_month_ago = float(ma200_series.iloc[-22]) if len(ma200_series) >= 22 else ma200

    def _proximity(margin_pct: float) -> float:
        """How far above threshold as % — positive means passing, negative failing."""
        return round(margin_pct, 1)

    # Per-criterion margin (positive = passing, shows how close to failing)
    m1 = (price / ma150 - 1) * 100
    m2 = (price / ma200 - 1) * 100
    m3 = (ma150 / ma200 - 1) * 100
    m4 = (ma200 / ma200_month_ago - 1) * 100
    m5 = min((ma50 / ma150 - 1) * 100, (ma50 / ma200 - 1) * 100)
    m6 = (price / ma50 - 1) * 100
    m7 = (price / (lo52 * 1.30) - 1) * 100   # Minervini's actual rule: 30%
    m8 = (price / (hi52 * 0.75) - 1) * 100

    criteria = [
        {
            'id': 1,
            'label': 'Price > 150-day MA',
            'result': price > ma150,
            'value': f"Price {price:.2f} | MA150 {ma150:.2f}",
            'note': 'Stock must be in upper half of long-term base',
            'proximity': _proximity(m1),
        },
        {
            'id': 2,
            'label': 'Price > 200-day MA',
            'result': price > ma200,
            'value': f"Price {price:.2f} | MA200 {ma200:.2f}",
            'note': 'Must be above the long-term trend line',
            'proximity': _proximity(m2),
        },
        {
            'id': 3,
            'label': '150-day MA > 200-day MA',
            'result': ma150 > ma200,
            'value': f"MA150 {ma150:.2f} | MA200 {ma200:.2f}",
            'note': 'Intermediate MA must be above long-term MA',
            'proximity': _proximity(m3),
        },
        {
            'id': 4,
            'label': '200-day MA trending up (1 month)',
            'result': ma200 > ma200_month_ago,
            'value': f"Current {ma200:.2f} | 1M ago {ma200_month_ago:.2f}",
            'note': 'Upward slope confirms sustained uptrend',
            'proximity': _proximity(m4),
        },
        {
            'id': 5,
            'label': '50-day MA > 150-day MA & 200-day MA',
            'result': ma50 > ma150 and ma50 > ma200,
            'value': f"MA50 {ma50:.2f} | MA150 {ma150:.2f} | MA200 {ma200:.2f}",
            'note': 'Short-term MA above both long-term MAs',
            'proximity': _proximity(m5),
        },
        {
            'id': 6,
            'label': 'Price > 50-day MA',
            'result': price > ma50,
            'value': f"Price {price:.2f} | MA50 {ma50:.2f}",
            'note': 'Must be in short-term uptrend',
            'proximity': _proximity(m6),
        },
        {
            'id': 7,
            'label': 'Price ≥ 30% above 52-week low',
            'result': price >= lo52 * 1.30,
            'value': f"Price {price:.2f} | 52W Low {lo52:.2f} (+{(price/lo52-1)*100:.1f}%)",
            'note': "Minervini's rule: stock has made meaningful upside progress",
            'proximity': _proximity(m7),
        },
        {
            'id': 8,
            'label': 'Price within 25% of 52-week high',
            'result': price >= hi52 * 0.75,
            'value': f"Price {price:.2f} | 52W High {hi52:.2f} ({(price/hi52-1)*100:.1f}%)",
            'note': 'Not extended too far from recent highs',
            'proximity': _proximity(m8),
        },
    ]

    pass_count = sum(c['result'] for c in criteria)
    qualified = pass_count >= 7

    return {
        'criteria': criteria,
        'pass_count': pass_count,
        'qualified': qualified,
        'price': price,
        'ma50': ma50,
        'ma150': ma150,
        'ma200': ma200,
        'hi52': hi52,
        'lo52': lo52,
    }


# ── Stage Analysis (Weinstein) ────────────────────────────────────────────────

def compute_stage(df: pd.DataFrame) -> dict:
    """
    Determine Weinstein stage using 30-week (150-day) MA slope and price position.

    Stage 1 — Basing:    price around flat MA, low volatility
    Stage 2 — Advancing: price above rising MA
    Stage 3 — Topping:   price near flat/turning MA after uptrend
    Stage 4 — Declining: price below falling MA
    """
    if df is None or df.empty or len(df) < 150:
        return {'stage': 0, 'label': 'N/A', 'color': '#888888'}

    close = df['Close'].dropna()
    price = float(close.iloc[-1])
    ma150 = _sma(close, 150)
    ma_val = float(ma150.iloc[-1])
    slope_up = _slope_positive(ma150, lookback=20)
    price_above = price > ma_val

    if price_above and slope_up:
        stage, label, color = 2, 'Stage 2 — Advancing', '#00FF41'
    elif not price_above and not slope_up:
        stage, label, color = 4, 'Stage 4 — Declining', '#FF4444'
    elif price_above and not slope_up:
        stage, label, color = 3, 'Stage 3 — Topping', '#FFD700'
    else:
        stage, label, color = 1, 'Stage 1 — Basing', '#888888'

    return {
        'stage': stage,
        'label': label,
        'color': color,
        'price_above_ma': price_above,
        'ma_slope_up': slope_up,
        'ma150': ma_val,
    }


# ── Relative Strength ─────────────────────────────────────────────────────────

def compute_rs(stock_df: pd.DataFrame, benchmark_df: pd.DataFrame) -> dict:
    """
    RS line = stock close / benchmark close.
    RS rank = percentile of 12-month return vs benchmark.
    """
    result = {
        'rs_line': pd.Series(dtype=float),
        'rs_6m': None, 'rs_12m': None,
        'rs_pct_6m': None, 'rs_pct_12m': None,
    }

    if stock_df is None or stock_df.empty or benchmark_df is None or benchmark_df.empty:
        return result

    sc = stock_df['Close'].dropna()
    bc = benchmark_df['Close'].dropna()

    # Normalise timezone — Alpaca returns tz-naive, yfinance tz-aware.
    # Strip timezone from both so index intersection works correctly.
    if hasattr(sc.index, 'tz') and sc.index.tz is not None:
        sc.index = sc.index.tz_localize(None)
    if hasattr(bc.index, 'tz') and bc.index.tz is not None:
        bc.index = bc.index.tz_localize(None)

    # Align on date only (drop time component if present)
    sc.index = pd.DatetimeIndex(sc.index.normalize())
    bc.index = pd.DatetimeIndex(bc.index.normalize())

    idx = sc.index.intersection(bc.index)
    if len(idx) < 10:
        return result

    sc, bc = sc.loc[idx], bc.loc[idx]
    rs_line = sc / bc

    def _ret(n_days):
        if len(sc) < n_days:
            return None
        r_stock = float(sc.iloc[-1] / sc.iloc[-n_days] - 1)
        r_bench = float(bc.iloc[-1] / bc.iloc[-n_days] - 1)
        return r_stock - r_bench

    result['rs_line'] = rs_line
    result['rs_6m'] = _ret(126)
    result['rs_12m'] = _ret(252)

    # Minervini-style RS rating (0-99) based on 12-month relative return
    # We approximate using the 12M relative return and a sigmoid-like scale
    rel12 = result['rs_12m']
    if rel12 is not None:
        # Map ±100% return range to 1-99
        clipped = max(-1.0, min(1.0, rel12))
        result['rs_pct_12m'] = int((clipped + 1.0) / 2.0 * 98) + 1

    rel6 = result['rs_6m']
    if rel6 is not None:
        clipped = max(-1.0, min(1.0, rel6))
        result['rs_pct_6m'] = int((clipped + 1.0) / 2.0 * 98) + 1

    return result


# ── VCP Detection ─────────────────────────────────────────────────────────────

def detect_vcp(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    Detect Volatility Contraction Pattern (VCP).
    VCP = series of price contractions STRICTLY PROGRESSIVELY SMALLER left to right.
    Any later contraction larger than an earlier one → Invalid VCP.

    Returns:
      vcp_detected: bool — True only when ALL contractions strictly decrease
      invalid_vcp: bool — True when we have 3+ contractions but NOT all decreasing
      contractions: int
      depths: list[float]
    """
    if df is None or df.empty or len(df) < lookback:
        return {'vcp_detected': False, 'invalid_vcp': False, 'contractions': 0, 'depths': []}

    sub = df.tail(lookback).copy()
    highs = sub['High'].values
    lows  = sub['Low'].values

    # Rolling 10-day windows, find local peak-to-trough contractions
    window = 10
    raw_contractions = []
    i = 0
    while i + window <= len(highs):
        w_high = highs[i:i+window].max()
        w_low  = lows[i:i+window].min()
        depth  = (w_high - w_low) / w_high if w_high > 0 else 0
        raw_contractions.append(depth)
        i += window

    if len(raw_contractions) < 3:
        return {
            'vcp_detected': False,
            'invalid_vcp': False,
            'contractions': 0,
            'depths': [round(d * 100, 1) for d in raw_contractions],
            'latest_depth': round(raw_contractions[-1] * 100, 1) if raw_contractions else 0,
        }

    # Check STRICT progressively smaller: every window smaller than the previous
    is_progressive = all(
        raw_contractions[j] < raw_contractions[j - 1]
        for j in range(1, len(raw_contractions))
    )

    # Count consecutive decreasing pairs from left before first violation
    consecutive_decreasing = 0
    for j in range(1, len(raw_contractions)):
        if raw_contractions[j] < raw_contractions[j - 1]:
            consecutive_decreasing += 1
        else:
            break

    # Valid VCP: all windows strictly decreasing
    vcp_detected = is_progressive and len(raw_contractions) >= 3
    # Invalid VCP: has multiple contractions but NOT all progressive
    invalid_vcp  = (not is_progressive) and consecutive_decreasing >= 2

    return {
        'vcp_detected': vcp_detected,
        'invalid_vcp':  invalid_vcp,
        'contractions': consecutive_decreasing,
        'depths': [round(d * 100, 1) for d in raw_contractions],
        'latest_depth': round(raw_contractions[-1] * 100, 1) if raw_contractions else 0,
    }


# ── Earnings Acceleration ─────────────────────────────────────────────────────

def compute_earnings_acceleration(quarterly_eps: list[float | None]) -> dict:
    """
    quarterly_eps: list of EPS values, oldest → newest.
    Returns acceleration flag and growth rates.
    """
    if not quarterly_eps or len(quarterly_eps) < 3:
        return {'accelerating': False, 'growth_rates': [], 'latest_growth': None}

    eps = [e for e in quarterly_eps if e is not None]
    if len(eps) < 3:
        return {'accelerating': False, 'growth_rates': [], 'latest_growth': None}

    # YoY growth for each quarter (vs same quarter prior year = 4 quarters back)
    growth_rates = []
    for i in range(4, len(eps)):
        curr = eps[i]
        prev = eps[i - 4]
        if prev and prev != 0:
            g = (curr - prev) / abs(prev) * 100
            growth_rates.append(round(g, 1))
        else:
            growth_rates.append(None)

    valid_rates = [r for r in growth_rates[-4:] if r is not None]
    if len(valid_rates) < 2:
        return {'accelerating': False, 'growth_rates': growth_rates, 'latest_growth': None}

    # Accelerating = each of last 2 growth rates higher than the one before
    accelerating = valid_rates[-1] > valid_rates[-2] if len(valid_rates) >= 2 else False
    # Strong acceleration = at least 3 consecutive increasing growth rates
    if len(valid_rates) >= 3:
        accelerating = valid_rates[-1] > valid_rates[-2] > valid_rates[-3]

    return {
        'accelerating': accelerating,
        'growth_rates': growth_rates,
        'latest_growth': valid_rates[-1] if valid_rates else None,
    }


# ── Composite SEPA Score ──────────────────────────────────────────────────────

def compute_sepa_score(
    trend: dict,
    stage: dict,
    rs: dict,
    vcp: dict,
    earnings_accel: dict,
    df: pd.DataFrame | None = None,
    earnings_fetched: bool = True,
) -> dict:
    """
    Weighted SEPA composite score out of 100.

    Weights:
      Trend Template    30 %
      RS Rank           20 %
      Earnings Accel    20 %
      VCP               15 %
      Volume / Stage    15 %

    earnings_fetched=False  → earnings data was never fetched (screener fast scan).
                              Score is out of 80 max (accel_score=0 naturally);
                              NO penalty cap is applied.
    earnings_fetched=True   → data was fetched. If present + not accelerating → cap 55.
                              If accelerating → full 100 possible.
    """
    # Trend score (0-30)
    pass_count = trend.get('pass_count', 0)
    trend_score = (pass_count / 8.0) * 30

    # RS score (0-20)
    rs12 = rs.get('rs_pct_12m') or 0
    rs_score = (rs12 / 99.0) * 20

    # Earnings acceleration score (0-20)
    accel = earnings_accel.get('accelerating', False)
    latest_g = earnings_accel.get('latest_growth')
    has_earnings_data = (
        latest_g is not None
        or len(earnings_accel.get('growth_rates', [])) > 0
    )
    latest_g_val = latest_g or 0
    accel_score = 0
    if accel:
        accel_score = 15 + min(5, latest_g_val / 20)
    elif latest_g_val > 20:
        accel_score = 10
    elif latest_g_val > 0:
        accel_score = 5

    # VCP score (0-15)
    vcp_score = 15 if vcp.get('vcp_detected') else (vcp.get('contractions', 0) / 3.0 * 10)
    vcp_score = min(15, vcp_score)

    # Volume / Stage score (0-15)
    stage_num = stage.get('stage', 0)
    stage_score = {2: 15, 1: 8, 3: 4, 4: 0}.get(stage_num, 0)

    total = trend_score + rs_score + accel_score + vcp_score + stage_score
    total = min(100, max(0, total))

    # Cap logic:
    # - earnings_fetched=False (screener fast scan): no cap; max natural score = 80
    # - earnings_fetched=True + data available + NOT accelerating: cap at 55
    #   (having data that shows no acceleration is a confirmed negative signal)
    if earnings_fetched and has_earnings_data and not accel:
        total = min(55, total)

    # Determine earnings_status for display
    if not earnings_fetched:
        earnings_status = 'Pending'
    elif not has_earnings_data:
        earnings_status = 'No Data'
    elif accel:
        earnings_status = 'Accelerating'
    else:
        earnings_status = 'Not Accelerating'

    grade = 'A' if total >= 80 else 'B' if total >= 60 else 'C' if total >= 40 else 'D'
    grade_color = {'A': '#00FF41', 'B': '#7FFF00', 'C': '#FFD700', 'D': '#FF4444'}[grade]

    return {
        'total': round(total, 1),
        'grade': grade,
        'grade_color': grade_color,
        'earnings_status': earnings_status,
        'breakdown': {
            'trend': round(trend_score, 1),
            'rs': round(rs_score, 1),
            'earnings': round(accel_score, 1),
            'vcp': round(vcp_score, 1),
            'volume_stage': round(stage_score, 1),
        },
    }
