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


# Holdco reorganizations: SEC moves the ticker to the new parent's CIK in
# company_tickers.json the moment the reorg completes, but the operating history
# (10-K/10-Q) stays on the predecessor CIK. The successor starts with zero
# periodic filings, so the ticker resolves correctly per SEC and still returns no
# fundamentals. Each entry records the event that caused it.
#
# BRIDGE, NOT PERMANENT. This works today because the successor has filed no
# 10-Q yet, so the predecessor holds the whole window, and because the
# edgartools gap-fill leg resolves by TICKER (not CIK) and returns a unified
# view across the reorg. Re-check when the successor files its first 10-Q -
# for ExxonMobil Holdings (2115436) that is expected around November 2026. At
# that point the correct series may span BOTH CIKs and this map needs to become
# a merge, or be removed once the successor has a full window of its own.
PREDECESSOR_CIK = {
    "XOM":  34088,   # ExxonMobil Holdings Corp (2115436) took the ticker 2026-07;
                     # zero 10-K/10-Q, files 8-K12B. History on Exxon Mobil Corp.
    "NVRI": 45876,   # Enviri Corp (2104052) registered via 10-12B; history on Harsco.
}


def resolve_ticker_to_cik(ticker: str) -> Optional[int]:
    """Resolves a stock ticker (e.g. 'AAPL') to its SEC CIK number, or None if unknown.

    Checks PREDECESSOR_CIK first: for the handful of tickers moved to a new CIK by
    a corporate reorganization, SEC's mapping is correct but points at an entity
    with no filing history, so the predecessor is what actually answers the
    fundamentals question.
    """
    key = ticker.upper()
    predecessor = PREDECESSOR_CIK.get(key)
    if predecessor is not None:
        return predecessor
    ticker_map = _load_ticker_map()
    return ticker_map.get(key)
