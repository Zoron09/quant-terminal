"""Field-by-field diff: quant-terminal's live /api/ticker output vs
code33-screener's own validated regression baseline JSON.

The baseline is the committed source of truth from the code33-screener project
(tools/regression_baseline.json) — values are NOT re-derived here, they're read
straight from that file and compared against what the running quant-terminal
server returns through utils/code33_adapter.py.

Run with the server up: python tools/verify_against_baseline.py [TICKER ...]
"""
import json
import sys
import urllib.request
from pathlib import Path

BASELINE = Path(r"C:\Users\Meet Singh\code33-screener\tools\regression_baseline.json")
SERVER = "http://localhost:8000"
DEFAULT_TICKERS = ["AAPL", "DELL", "WMT"]


def fetch_api(ticker: str) -> dict:
    with urllib.request.urlopen(f"{SERVER}/api/ticker/{ticker}", timeout=900) as r:
        return json.loads(r.read().decode())


def main() -> int:
    tickers = sys.argv[1:] or DEFAULT_TICKERS
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    total_compared = 0
    mismatches = []

    for ticker in tickers:
        if ticker not in baseline:
            print(f"{ticker}: NOT IN BASELINE — skipped")
            continue

        api = fetch_api(ticker)
        base_rev = {r["period_end"]: r["value"] for r in baseline[ticker]["revenue"]}
        base_npm = {r["period_end"]: r["net_margin_pct"] for r in baseline[ticker]["margin"]}

        api_rev = dict(zip(api.get("rev_end_dates", []), api.get("rev", [])))
        api_npm = dict(zip(api.get("npm_ends", []), api.get("npm", [])))

        print(f"\n=== {ticker} (status={api.get('status')}) ===")
        print(f"{'quarter':<12}{'field':<8}{'baseline':>20}{'server':>20}  result")

        shared_rev = sorted(set(base_rev) & set(api_rev), reverse=True)
        shared_npm = sorted(set(base_npm) & set(api_npm), reverse=True)

        for q in shared_rev:
            b, a = base_rev[q], api_rev[q]
            same = (b == a)
            total_compared += 1
            if not same:
                mismatches.append((ticker, q, "revenue", b, a))
            print(f"{q:<12}{'revenue':<8}{b:>20,.0f}{a:>20,.0f}  {'MATCH' if same else 'MISMATCH'}")

        for q in shared_npm:
            b, a = base_npm[q], api_npm[q]
            same = (b == a)
            total_compared += 1
            if not same:
                mismatches.append((ticker, q, "net_margin", b, a))
            print(f"{q:<12}{'margin':<8}{b:>20.2f}{a:>20.2f}  {'MATCH' if same else 'MISMATCH'}")

        only_api_rev = sorted(set(api_rev) - set(base_rev), reverse=True)
        only_base_rev = sorted(set(base_rev) - set(api_rev), reverse=True)
        if only_api_rev:
            print(f"  [info] quarters on server but not in baseline: {only_api_rev}")
        if only_base_rev:
            print(f"  [info] quarters in baseline but not on server: {only_base_rev}")

    print(f"\n{'=' * 60}")
    print(f"fields compared: {total_compared}")
    if mismatches:
        print(f"MISMATCHES: {len(mismatches)}")
        for t, q, f, b, a in mismatches:
            print(f"  {t} {q} {f}: baseline={b!r} server={a!r}")
        return 1
    print("ALL FIELDS MATCH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
