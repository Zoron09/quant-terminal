"""Ticker -> CIK resolution.

secfsdstools only supports company-name search (IndexSearch.find_company_by_name) and
lookup by CIK (CompanyIndexReader). It has no ticker index, so we resolve tickers
ourselves against SEC's public company_tickers.json, cached locally.
"""
import json
import time
from pathlib import Path
from typing import Optional

import requests

from secfsdstools.a_config.configmgt import ConfigurationManager

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 1 week

# parents[1], not parents[2]: upstream this file sits at <repo>/src/code33/, so
# it needed three levels to reach the repo root. Vendored into quant-terminal it
# sits at <repo>/code33/, one level shallower — leaving parents[2] would resolve
# to the PARENT of the repo (the user's home directory) and silently write the
# SEC ticker cache outside the project. This is the ONLY deviation from a
# byte-identical copy of code33-screener/src/code33/ticker_lookup.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = PROJECT_ROOT / "data" / "company_tickers.json"


def _download_ticker_file() -> dict:
    config = ConfigurationManager.read_config_file()
    headers = {"User-Agent": config.user_agent_email}
    response = requests.get(TICKER_URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def _load_ticker_map() -> dict:
    """Returns {ticker_upper: cik_int}, downloading/refreshing the cache if stale."""
    is_stale = (
        not CACHE_PATH.exists()
        or (time.time() - CACHE_PATH.stat().st_mtime) > CACHE_MAX_AGE_SECONDS
    )

    if is_stale:
        raw = _download_ticker_file()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(raw), encoding="utf-8")
    else:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    return {entry["ticker"].upper(): int(entry["cik_str"]) for entry in raw.values()}


def resolve_ticker_to_cik(ticker: str) -> Optional[int]:
    """Resolves a stock ticker (e.g. 'AAPL') to its SEC CIK number, or None if unknown."""
    ticker_map = _load_ticker_map()
    return ticker_map.get(ticker.upper())
