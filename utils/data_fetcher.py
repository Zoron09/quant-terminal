import yfinance as yf
import streamlit as st
import pandas as pd

# Finnhub: secondary source for analyst/earnings data (US only)
try:
    from utils.finnhub_client import (
        fh_recommendations, fh_price_target, fh_upgrades,
        fh_insider_transactions, fh_earnings_surprises, FINNHUB_KEY,
    )
    _HAS_FINNHUB = bool(FINNHUB_KEY)
except Exception:
    _HAS_FINNHUB = False

# Alpaca: primary source for US price history and real-time data
try:
    from utils.alpaca_client import get_bars as _alpaca_bars, _HAS_ALPACA
except Exception:
    _HAS_ALPACA = False
    _alpaca_bars = None


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _period_to_years(period: str) -> int:
    """Convert yfinance period string to approximate years for Alpaca."""
    mapping = {'1d': 1, '5d': 1, '1mo': 1, '3mo': 1, '6mo': 1,
               '1y': 1, '2y': 2, '3y': 3, '5y': 5, '10y': 7, 'max': 7}
    return mapping.get(period, 2)


@st.cache_data(ttl=900, show_spinner=False)
def get_ticker_info(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)
def get_financials(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    result = {}
    for key, attr in [
        ('income_annual', 'financials'),
        ('income_quarterly', 'quarterly_financials'),
        ('balance_annual', 'balance_sheet'),
        ('balance_quarterly', 'quarterly_balance_sheet'),
        ('cashflow_annual', 'cashflow'),
        ('cashflow_quarterly', 'quarterly_cashflow'),
    ]:
        result[key] = _safe(lambda a=attr: getattr(t, a))
    return result


@st.cache_data(ttl=900, show_spinner=False)
def get_price_history(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Price history routing:
      US stocks  → Alpaca (primary, real-time IEX, 5+ yr history) with yfinance fallback
      Indian/ETF → yfinance only
    """
    is_us = '.' not in ticker and not ticker.startswith('^')

    if is_us and _HAS_ALPACA and _alpaca_bars and interval == '1d':
        years = _period_to_years(period)
        df = _alpaca_bars(ticker.upper(), years=years)
        if df is not None and not df.empty:
            return df

    # yfinance fallback (Indian stocks, ETFs, indices, or Alpaca unavailable)
    try:
        t  = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def get_earnings_data(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    result = {}
    result['earnings_dates'] = _safe(lambda: t.earnings_dates)
    result['earnings_history'] = _safe(lambda: t.earnings_history)
    result['calendar'] = _safe(lambda: t.calendar)
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def get_analyst_data(ticker: str) -> dict:
    """Analyst data — yfinance primary, Finnhub fills gaps for US tickers."""
    t = yf.Ticker(ticker)
    data = {
        'recommendations': _safe(lambda: t.recommendations),
        'analyst_price_targets': _safe(lambda: t.analyst_price_targets),
        'upgrades_downgrades': _safe(lambda: t.upgrades_downgrades),
        'earnings_estimate': _safe(lambda: t.earnings_estimate),
        'revenue_estimate': _safe(lambda: t.revenue_estimate),
        'recommendations_summary': _safe(lambda: t.recommendations_summary),
        # Finnhub-sourced fields (US stocks only)
        'fh_recommendations': None,
        'fh_price_target': None,
        'fh_upgrades': None,
    }

    if _HAS_FINNHUB and '.' not in ticker:  # US stocks only
        sym = ticker.upper()
        data['fh_recommendations'] = fh_recommendations(sym)
        data['fh_price_target']    = fh_price_target(sym)
        data['fh_upgrades']        = fh_upgrades(sym)

    return data


@st.cache_data(ttl=3600, show_spinner=False)
def get_ownership_data(ticker: str) -> dict:
    """Ownership data — yfinance primary, Finnhub insider transactions for US."""
    t = yf.Ticker(ticker)
    data = {
        'insider_transactions': _safe(lambda: t.insider_transactions),
        'institutional_holders': _safe(lambda: t.institutional_holders),
        'mutualfund_holders': _safe(lambda: t.mutualfund_holders),
        'major_holders': _safe(lambda: t.major_holders),
        'fh_insider_transactions': None,
    }

    if _HAS_FINNHUB and '.' not in ticker:
        raw = fh_insider_transactions(ticker.upper())
        if raw and isinstance(raw, dict):
            rows = raw.get('data', [])
            if rows:
                data['fh_insider_transactions'] = pd.DataFrame(rows)

    return data


@st.cache_data(ttl=3600, show_spinner=False)
def get_earnings_surprises_finnhub(ticker: str) -> list | None:
    """Finnhub earnings surprise history — faster and more complete than yfinance."""
    if not _HAS_FINNHUB or '.' in ticker:
        return None
    return fh_earnings_surprises(ticker.upper())


def detect_market(ticker: str) -> str:
    return 'IN' if '.' in ticker else 'US'


def get_benchmark(ticker: str) -> str:
    return '^NSEI' if detect_market(ticker) == 'IN' else '^GSPC'
