"""
Code 33 Screener — Minervini Fundamental Signal
================================================
Reads a CSV of symbols (from TradingView SEPA screener),
checks each ticker for 3 consecutive quarters where ALL THREE hold:
  1. EPS YoY growth rate ACCELERATING  (Q YoY% > prior Q YoY%)
  2. Revenue YoY growth rate ACCELERATING
  3. Net Profit Margin EXPANDING        (Q margin > prior Q margin)

Data flow: Shared Code 33 engine (utils/code33_engine.py)
Run: python code33_screener.py
"""

import os
import sys
import time
import warnings
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

# ── Add project root to path ──────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Config ────────────────────────────────────────────────────────────────────
# Accept CSV path as command-line argument, or use default
if len(sys.argv) > 1:
    CSV_PATH = sys.argv[1]
else:
    CSV_PATH = r"C:\Users\Meet Singh\Downloads\Minervini builder_2026-04-17.csv"

# Auto-generate output path alongside the input CSV
_base = os.path.splitext(CSV_PATH)[0]
OUTPUT_PATH = _base + "_Code33_Results.csv"

ENV_PATH = r"C:\Users\Meet Singh\quant-terminal\.env"
load_dotenv(ENV_PATH)

# Finnhub free tier: 60 calls/min → sleep 1.1s between calls to be safe
FH_SLEEP = 1.1

# ── Import shared Code 33 engine ──────────────────────────────────────────────
from utils.code33_engine import get_code33_data, _c33_status


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  CODE 33 SCREENER - Minervini Fundamental Signal")
    print(f"  Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  Engine: utils/code33_engine.py (unified)")
    print("=" * 65)

    # Load CSV
    df_csv  = pd.read_csv(CSV_PATH)
    tickers = df_csv["Symbol"].dropna().str.strip().tolist()
    name_map = dict(zip(df_csv["Symbol"].str.strip(), df_csv["Description"]))
    print(f"\nLoaded {len(tickers)} tickers from CSV.\n")

    results      = []
    failed       = []   # errors
    no_qual      = []   # doesn't meet Code 33
    insufficient = []   # not enough data

    start = time.time()

    for i, symbol in enumerate(tickers, 1):
        # Progress every 50 tickers
        if i % 50 == 0:
            elapsed   = time.time() - start
            rate      = elapsed / i
            remaining = rate * (len(tickers) - i)
            print(f"  [{i:>3}/{len(tickers)}] | Qualifiers: {len(results):>3} | "
                  f"ETA: {remaining/60:.1f} min")

        try:
            data = get_code33_data(symbol)
        except Exception:
            failed.append(symbol)
            continue

        rev_yoy  = data.get('rev_yoy', [])
        eps_yoy  = data.get('eps_yoy', [])
        npm_vals = data.get('npm', [])
        rev_lbl  = data.get('rev_labels', [])
        eps_lbl  = data.get('eps_labels', [])
        eps_raw  = data.get('eps', [])
        is_us    = data.get('is_us', True)
        sect_ex  = data.get('sector_excluded', False)

        if not is_us or sect_ex:
            no_qual.append(symbol)
            continue

        # Pre-profit check: all 6 latest EPS negative = NOT APPLICABLE
        is_preprofit = False
        if len(eps_raw) >= 6:
            last6 = eps_raw[-6:]
            if all(v is not None and v < 0 for v in last6):
                is_preprofit = True

        if is_preprofit:
            no_qual.append(symbol)
            continue

        if len(rev_yoy) < 3 or len(eps_yoy) < 3 or len(npm_vals) < 3:
            insufficient.append(symbol)
            continue

        eps3 = eps_yoy[-3:]
        rev3 = rev_yoy[-3:]
        npm3 = npm_vals[-3:]

        eps_status, _, _ = _c33_status(eps3)
        rev_status, _, _ = _c33_status(rev3)

        npm_d1 = npm3[1] - npm3[0]
        npm_d2 = npm3[2] - npm3[1]
        if npm_d1 < 0 or npm_d2 < 0:
            npm_status = 'red'
        elif npm3[0] < 0 and npm3[1] < 0 and npm3[2] < 0:
            npm_status = 'not_applicable'
        else:
            npm_status = 'green' if (npm_d1 > 0 and npm_d2 > 0) else 'yellow'

        if eps_status != 'green' or rev_status != 'green' or npm_status != 'green':
            no_qual.append(symbol)
            continue

        company  = name_map.get(symbol, "")
        q_period = f"{rev_lbl[-3] if len(rev_lbl) >= 3 else '?'}->{rev_lbl[-1] if rev_lbl else '?'}"
        result   = {
            "Ticker":              symbol,
            "Company":             company,
            "Source":              data.get('sources', {}).get('rev', 'FMP|EDGAR'),
            "Qualifying Period":   q_period,
            "Window End":          rev_lbl[-1] if rev_lbl else '',
            "EPS YoY Trend (%)":   f"{eps3[0]:.1f} -> {eps3[1]:.1f} -> {eps3[2]:.1f}",
            "Rev YoY Trend (%)":   f"{rev3[0]:.1f} -> {rev3[1]:.1f} -> {rev3[2]:.1f}",
            "Net Margin Trend (%)": f"{npm3[0]:.2f} -> {npm3[1]:.2f} -> {npm3[2]:.2f}",
            "Latest EPS YoY":      round(eps3[2], 1),
            "Latest Rev YoY":      round(rev3[2], 1),
            "Latest NPM (%)":      round(npm3[2], 2),
        }
        results.append(result)
        print(f"  [+] {symbol:<8} {company[:35]:<35} | {q_period} | "
              f"EPS:{eps3[2]:>7.1f}% "
              f"Rev:{rev3[2]:>7.1f}% "
              f"NPM:{npm3[2]:>6.2f}%")

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print("\n" + "=" * 65)
    print(f"  COMPLETE in {elapsed/60:.1f} min")
    print(f"  Screened:          {len(tickers)}")
    print(f"  Code 33 qualified: {len(results)}")
    print(f"  No signal:         {len(no_qual)}")
    print(f"  Insufficient data: {len(insufficient)}")
    print(f"  Errors:            {len(failed)}")
    print("=" * 65)

    if not results:
        print("\nNo stocks qualified for Code 33.")
        return

    # ── Save CSV ─────────────────────────────────────────────────────────────
    out_df = pd.DataFrame(results)
    col_order = [
        "Ticker", "Company", "Source",
        "Qualifying Period", "Window End",
        "EPS YoY Trend (%)", "Rev YoY Trend (%)", "Net Margin Trend (%)",
        "Latest EPS YoY", "Latest Rev YoY", "Latest NPM (%)",
    ]
    out_df = out_df[[c for c in col_order if c in out_df.columns]]
    out_df = out_df.sort_values("Latest EPS YoY", ascending=False)

    out_df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nResults saved: {OUTPUT_PATH}\n")

    # ── Print table ───────────────────────────────────────────────────────────
    print("\n=== CODE 33 QUALIFYING STOCKS ===\n")
    pd.set_option("display.max_colwidth", 35)
    pd.set_option("display.width", 200)
    print(out_df[["Ticker", "Company", "Qualifying Period", "Window End",
                   "EPS YoY Trend (%)", "Rev YoY Trend (%)",
                   "Net Margin Trend (%)"]].to_string(index=False))

    # Failed tickers (for reference)
    if failed:
        print(f"\nTickers with errors ({len(failed)}):")
        print(", ".join(failed))


if __name__ == "__main__":
    main()
