"""
Code 33 Batch Scanner — ThreadPoolExecutor runner
====================================================
Reads the Symbol column from a TradingView/Minervini-builder CSV export,
runs get_code33_data() on every ticker concurrently (max_workers=10),
and writes a flat results CSV with the last 3 Rev YoY% / Net Margin% quarters,
the data source used (secfsdstools / EDGAR-edgartools / FMP|EDGAR), and the
Code33 status for every ticker (including errors/insufficient). Rows are
written to disk as each ticker completes, not buffered until the end.

Data flow: Shared Code 33 engine (utils/code33_engine.py)
Run: python tools/run_c33_batch.py
"""

import os
import sys
import csv
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

# ── Paths (resolved relative to repo root, not cwd) ────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

INPUT_CSV  = os.path.join(ROOT, "Minervini builder Managed copy_2026-06-23.csv")
OUTPUT_CSV = os.path.join(ROOT, "Code33_Results_2026-06-23.csv")

from utils.code33_engine import get_code33_data
from tools.preflight_checks import run_preflight

MAX_WORKERS = 10
FIELDNAMES = ['Ticker', 'Status', 'Rev_YoY_Q1', 'Rev_YoY_Q2', 'Rev_YoY_Q3',
              'NPM_Q1', 'NPM_Q2', 'NPM_Q3', 'Source', 'PreflightFlags']


def _last3(vals):
    """Last 3 non-None values from a list, oldest-to-newest. Pads with '' if short."""
    if not vals:
        return ['', '', '']
    clean = [v for v in vals if v is not None]
    last3 = clean[-3:]
    last3 = [''] * (3 - len(last3)) + last3
    return [round(v, 2) if v != '' else '' for v in last3]


def scan_one(ticker: str) -> dict:
    """Run get_code33_data for one ticker. Never raises — caller handles all errors."""
    data = get_code33_data(ticker)
    status = str(data.get('status', 'insufficient') or 'insufficient').upper()
    rev_q = _last3(data.get('rev_yoy', []))
    npm_q = _last3(data.get('npm', []))
    sources = data.get('sources', {}) or {}
    source = f"rev:{sources.get('rev', '?')}|ni:{sources.get('ni', '?')}"
    flags = run_preflight(ticker, data)
    return {
        'Ticker': ticker,
        'Status': status,
        'Rev_YoY_Q1': rev_q[0], 'Rev_YoY_Q2': rev_q[1], 'Rev_YoY_Q3': rev_q[2],
        'NPM_Q1': npm_q[0], 'NPM_Q2': npm_q[1], 'NPM_Q3': npm_q[2],
        'Source': source,
        'PreflightFlags': '; '.join(flags),
    }


def main():
    print("=" * 65)
    print("  CODE 33 BATCH SCAN (ThreadPoolExecutor, max_workers=10)")
    print(f"  Input:  {INPUT_CSV}")
    print(f"  Output: {OUTPUT_CSV}")
    print("=" * 65)

    import pandas as pd
    df = pd.read_csv(INPUT_CSV)
    tickers = df["Symbol"].dropna().str.strip().str.upper().tolist()
    total = len(tickers)
    print(f"\nLoaded {total} tickers from CSV.\n")

    counts = {'GREEN': 0, 'YELLOW': 0, 'RED': 0, 'INSUFFICIENT': 0, 'ERROR': 0}
    green_tickers = []

    start = time.time()
    done = 0

    # Write incrementally: header now, one row per ticker as it completes.
    out_f = open(OUTPUT_CSV, 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
    writer.writeheader()
    out_f.flush()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_ticker = {pool.submit(scan_one, t): t for t in tickers}

        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                row = future.result()
            except Exception:
                # Catch-all: never let a single ticker crash the batch.
                row = {
                    'Ticker': ticker, 'Status': 'ERROR',
                    'Rev_YoY_Q1': '', 'Rev_YoY_Q2': '', 'Rev_YoY_Q3': '',
                    'NPM_Q1': '', 'NPM_Q2': '', 'NPM_Q3': '', 'Source': '',
                    'PreflightFlags': '',
                }

            writer.writerow(row)
            out_f.flush()

            counts[row['Status']] = counts.get(row['Status'], 0) + 1
            if row['Status'] == 'GREEN':
                green_tickers.append((row['Ticker'], row['PreflightFlags']))

            done += 1
            if done % 50 == 0 or done == total:
                elapsed = time.time() - start
                rate = elapsed / done
                remaining = rate * (total - done)
                print(f"  [{done:>4}/{total}] | GREEN:{counts['GREEN']:>3} "
                      f"YELLOW:{counts['YELLOW']:>3} RED:{counts['RED']:>3} "
                      f"INSUFF:{counts['INSUFFICIENT']:>3} ERR:{counts['ERROR']:>3} | "
                      f"ETA: {remaining/60:.1f} min")

    out_f.close()
    elapsed = time.time() - start

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  COMPLETE in {elapsed/60:.1f} min")
    print(f"  Total:        {total}")
    print(f"  GREEN:        {counts['GREEN']}")
    print(f"  YELLOW:       {counts['YELLOW']}")
    print(f"  RED:          {counts['RED']}")
    print(f"  INSUFFICIENT: {counts['INSUFFICIENT']}")
    print(f"  ERROR:        {counts['ERROR']}")
    print("=" * 65)
    print(f"\nResults saved: {OUTPUT_CSV}\n")

    clean_green = sorted(t for t, flags in green_tickers if not flags)
    flagged_green = sorted((t, flags) for t, flags in green_tickers if flags)

    print("=== GREEN TICKERS ===")
    print(", ".join(clean_green) if clean_green else "(none)")

    print("\n=== GREEN — NEEDS REVIEW (pre-flight flagged, not excluded) ===")
    if flagged_green:
        for ticker, flags in flagged_green:
            print(f"  {ticker}: {flags}")
    else:
        print("(none)")


if __name__ == "__main__":
    main()
