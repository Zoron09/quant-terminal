"""
SEC EDGAR free API — real-time insider filings (Form 4) and recent filings.
No API key required. Uses https://data.sec.gov and https://efts.sec.gov
"""
import streamlit as st
import requests
import pandas as pd

HEADERS = {'User-Agent': 'QuantTerminal research@quant-terminal.local'}


def _get(url: str, params: dict | None = None):
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_cik(ticker: str) -> str | None:
    """Resolve ticker → CIK via EDGAR company search."""
    data = _get('https://efts.sec.gov/LATEST/search-index?q=%22' + ticker + '%22&dateRange=custom&startdt=2020-01-01&forms=4')
    # Fallback: use the company facts lookup
    mapping = _get('https://www.sec.gov/files/company_tickers.json')
    if not mapping:
        return None
    ticker_up = ticker.upper().split('.')[0]  # strip .NS etc.
    for entry in mapping.values():
        if entry.get('ticker', '').upper() == ticker_up:
            return str(entry['cik_str']).zfill(10)
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_recent_filings(ticker: str, form_types: list | None = None) -> pd.DataFrame:
    """Return recent SEC filings for a ticker as a DataFrame."""
    cik = get_cik(ticker)
    if not cik:
        return pd.DataFrame()

    data = _get(f'https://data.sec.gov/submissions/CIK{cik}.json')
    if not data:
        return pd.DataFrame()

    recent = data.get('filings', {}).get('recent', {})
    if not recent:
        return pd.DataFrame()

    df = pd.DataFrame({
        'form': recent.get('form', []),
        'filingDate': recent.get('filingDate', []),
        'reportDate': recent.get('reportDate', []),
        'accessionNumber': recent.get('accessionNumber', []),
        'primaryDocument': recent.get('primaryDocument', []),
    })

    if form_types:
        df = df[df['form'].isin(form_types)]

    df['url'] = df.apply(
        lambda r: f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                  f"{r['accessionNumber'].replace('-', '')}/{r['primaryDocument']}",
        axis=1,
    )
    return df.head(50).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_insider_filings(ticker: str) -> pd.DataFrame:
    """Form 4 insider transaction filings."""
    return get_recent_filings(ticker, form_types=['4', '4/A'])


@st.cache_data(ttl=86400, show_spinner=False)
def get_key_filings(ticker: str) -> pd.DataFrame:
    """10-K, 10-Q, 8-K filings."""
    return get_recent_filings(ticker, form_types=['10-K', '10-Q', '8-K'])
