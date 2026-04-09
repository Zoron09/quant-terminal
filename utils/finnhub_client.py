"""
Finnhub API client — secondary data source for analyst ratings,
insider transactions, and earnings estimates.
"""
import os
import streamlit as st
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

FINNHUB_KEY = os.getenv('FINNHUB_API_KEY', '')
BASE = 'https://finnhub.io/api/v1'


def _get(endpoint: str, params: dict) -> dict | list | None:
    if not FINNHUB_KEY:
        return None
    try:
        params['token'] = FINNHUB_KEY
        r = requests.get(f'{BASE}/{endpoint}', params=params, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fh_recommendations(symbol: str):
    """[{period, strongBuy, buy, hold, sell, strongSell}, ...]"""
    return _get('stock/recommendation', {'symbol': symbol})


@st.cache_data(ttl=3600, show_spinner=False)
def fh_price_target(symbol: str):
    """{lastUpdated, targetHigh, targetLow, targetMean, targetMedian}"""
    return _get('stock/price-target', {'symbol': symbol})


@st.cache_data(ttl=3600, show_spinner=False)
def fh_upgrades(symbol: str):
    """[{symbol, gradeDate, fromGrade, toGrade, company, action}, ...]"""
    return _get('stock/upgrade-downgrade', {'symbol': symbol})


@st.cache_data(ttl=3600, show_spinner=False)
def fh_insider_transactions(symbol: str):
    """{data: [{name, share, change, transactionDate, transactionCode, value}, ...]}"""
    return _get('stock/insider-transactions', {'symbol': symbol})


@st.cache_data(ttl=3600, show_spinner=False)
def fh_earnings_surprises(symbol: str):
    """[{period, actual, estimate, surprise, surprisePercent}, ...]"""
    return _get('stock/earnings', {'symbol': symbol})


@st.cache_data(ttl=3600, show_spinner=False)
def fh_basic_financials(symbol: str):
    """{metric: {...}, series: {...}}"""
    return _get('stock/metric', {'symbol': symbol, 'metric': 'all'})


@st.cache_data(ttl=86400, show_spinner=False)
def fh_peers(symbol: str):
    """[ticker, ...]"""
    result = _get('stock/peers', {'symbol': symbol})
    return result if isinstance(result, list) else []
