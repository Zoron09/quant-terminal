"""
Watchlist ticker audit vs SEC's current ticker map
====================================================
Cross-checks every ticker in data/sp500_tickers.json (the tracked universe the
live screener scans) against SEC's own company_tickers.json. Reports any
ticker that no longer resolves to a CIK — usually a rename (ABC -> COR/
Cencora) or a delisting/take-private (WBA) — so the stale ones can be cleaned
out of the watchlist. This is a one-time/occasional maintenance check, not
part of the per-ticker Code33 pipeline (see check_ticker_resolution in
tools/preflight_checks.py for the per-ticker version wired into run_preflight).

Run: .venv/Scripts/python.exe tools/watchlist_ticker_audit.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from utils.sec_edgar import get_cik

UNIVERSE_PATH = os.path.join(ROOT, "data", "sp500_tickers.json")


def main():
    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)

    stale = []
    for ticker in universe:
        cik = get_cik(ticker)
        if cik is None:
            stale.append(ticker)

    print(f"{len(universe)} tickers checked against SEC's current company_tickers.json")
    if stale:
        print(f"\n{len(stale)} no longer resolve (renamed / delisted / taken private):")
        for t in stale:
            print(f"  {t}")
    else:
        print("\nall tickers resolve cleanly")


if __name__ == "__main__":
    main()
