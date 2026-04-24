"""
Code 33 Screener — Minervini Fundamental Signal
================================================
Reads a CSV of symbols (from TradingView SEPA screener),
checks each ticker for 3 consecutive quarters where ALL THREE hold:
  1. EPS YoY growth rate ACCELERATING  (Q YoY% > prior Q YoY%)
  2. Revenue YoY growth rate ACCELERATING
  3. Net Profit Margin EXPANDING        (Q margin > prior Q margin)

Data flow: Finnhub basic_financials (primary) → yfinance (fallback)
Run: python code33_screener.py
"""

import os
import sys
import time
import requests
import warnings
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
CSV_PATH    = r"C:\Users\Meet Singh\Downloads\Minervini builder_2026-04-17.csv"
OUTPUT_PATH = r"C:\Users\Meet Singh\Downloads\Code33_Results_2026-04-17.csv"
ENV_PATH    = r"C:\Users\Meet Singh\quant-terminal\.env"

load_dotenv(ENV_PATH)
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
FH_BASE     = "https://finnhub.io/api/v1"

# Finnhub free tier: 60 calls/min → sleep 1.1s between calls to be safe
FH_SLEEP    = 1.1
YF_SLEEP    = 0.4

# ── Helpers ───────────────────────────────────────────────────────────────────

def quarter_from_date(date_str: str) -> tuple[int, int] | None:
    """Convert '2024-09-30' → (2024, 3).  Returns None on parse error."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        q = (dt.month - 1) // 3 + 1
        return dt.year, q
    except Exception:
        return None


def series_to_df(series_list: list, col_name: str) -> pd.DataFrame:
    """
    Convert Finnhub quarterly series [{"period": "...", "v": ...}, ...]
    to DataFrame with columns: year, quarter, col_name.
    """
    rows = []
    for item in series_list:
        yq = quarter_from_date(item.get("period", ""))
        if yq is None:
            continue
        val = item.get("v")
        if val is None or not np.isfinite(float(val)):
            continue
        rows.append({"year": yq[0], "quarter": yq[1], col_name: float(val)})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates(["year", "quarter"])
    return df.sort_values(["year", "quarter"]).reset_index(drop=True)


# ── Data fetchers ──────────────────────────────────────────────────────────────

def fh_get(endpoint: str, params: dict) -> dict | None:
    if not FINNHUB_KEY:
        return None
    try:
        params["token"] = FINNHUB_KEY
        r = requests.get(f"{FH_BASE}/{endpoint}", params=params, timeout=10)
        if r.status_code == 429:
            time.sleep(5)
            r = requests.get(f"{FH_BASE}/{endpoint}", params=params, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def get_finnhub_quarterly(symbol: str) -> pd.DataFrame | None:
    """
    Pull quarterly EPS, Revenue, Net Margin from Finnhub basic_financials.
    Returns DataFrame with columns: year, quarter, eps, revenue, npm
    (needs ≥ 7 rows for meaningful YoY comparison across 3 consecutive quarters)
    """
    data = fh_get("stock/metric", {"symbol": symbol, "metric": "all"})
    time.sleep(FH_SLEEP)

    if not data or "series" not in data:
        return None

    q_series = data.get("series", {}).get("quarterly", {})
    if not q_series:
        return None

    # EPS — try epsBasic first, then eps
    eps_raw   = q_series.get("epsBasic") or q_series.get("eps")
    rev_raw   = q_series.get("revenue") or q_series.get("salesPerShare")  # salesPerShare won't work for NPM
    npm_raw   = q_series.get("netMargin")  # Finnhub netMargin = NetIncome/Revenue (decimal)

    if not eps_raw or not rev_raw or not npm_raw:
        return None

    df_eps  = series_to_df(eps_raw,  "eps")
    df_rev  = series_to_df(rev_raw,  "revenue")
    df_npm  = series_to_df(npm_raw,  "npm")

    if df_eps.empty or df_rev.empty or df_npm.empty:
        return None

    # Merge on year+quarter
    df = df_eps.merge(df_rev, on=["year", "quarter"]).merge(df_npm, on=["year", "quarter"])
    df = df.sort_values(["year", "quarter"]).reset_index(drop=True)

    if len(df) < 7:
        return None
    return df


def get_yfinance_quarterly(symbol: str) -> pd.DataFrame | None:
    """
    Pull quarterly GAAP financials from yfinance.
    Returns DataFrame with columns: year, quarter, eps, revenue, npm
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        inc = ticker.quarterly_income_stmt
        time.sleep(YF_SLEEP)

        if inc is None or inc.empty:
            return None

        rows = []
        for col in inc.columns:
            try:
                year    = col.year
                quarter = (col.month - 1) // 3 + 1

                # EPS (GAAP basic)
                eps = None
                for lbl in ["Basic EPS", "Diluted EPS", "EPS"]:
                    if lbl in inc.index:
                        v = inc.loc[lbl, col]
                        if pd.notna(v) and np.isfinite(float(v)):
                            eps = float(v)
                            break

                # Revenue
                revenue = None
                for lbl in ["Total Revenue", "Revenue", "Net Revenue",
                             "Operating Revenue"]:
                    if lbl in inc.index:
                        v = inc.loc[lbl, col]
                        if pd.notna(v) and np.isfinite(float(v)) and float(v) != 0:
                            revenue = float(v)
                            break

                # Net Income (GAAP)
                net_income = None
                for lbl in ["Net Income", "Net Income Common Stockholders",
                             "Net Income Including Noncontrolling Interests"]:
                    if lbl in inc.index:
                        v = inc.loc[lbl, col]
                        if pd.notna(v) and np.isfinite(float(v)):
                            net_income = float(v)
                            break

                if eps is None or revenue is None or net_income is None:
                    continue

                npm = net_income / revenue  # decimal

                rows.append({
                    "year":    year,
                    "quarter": quarter,
                    "eps":     eps,
                    "revenue": revenue,
                    "npm":     npm,
                    "_date":   col,
                })
            except Exception:
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.sort_values("_date").drop_duplicates(["year", "quarter"])
        df = df.drop(columns=["_date"]).sort_values(["year", "quarter"]).reset_index(drop=True)

        if len(df) < 7:
            return None
        return df

    except Exception:
        return None


# ── Code 33 logic ─────────────────────────────────────────────────────────────

def compute_code33(df: pd.DataFrame,
                   min_end_year: int = 2024,
                   min_end_quarter: int = 3) -> dict | None:
    """
    Given a DataFrame with: year, quarter, eps, revenue, npm
    Returns dict with qualifying info, or None if no 3-quarter window qualifies.

    Only returns windows whose LAST quarter is >= (min_end_year, min_end_quarter)
    — default = Q3 2024 (~18 months ago) so we capture current-cycle momentum.

    Logic:
      1. Compute YoY growth for EPS and Revenue (same-quarter prior year).
      2. For each 3 consecutive quarters in the YoY series:
         - EPS YoY accelerating:   yoy[i+1] > yoy[i]  AND  yoy[i+2] > yoy[i+1]
         - Rev YoY accelerating:   same
         - NPM expanding:          npm[i+1] > npm[i]   AND  npm[i+2] > npm[i+1]
      3. Return the MOST RECENT qualifying window (within recency filter).
    """
    df = df.sort_values(["year", "quarter"]).reset_index(drop=True)

    # Build lookup dict
    lkp = {(int(r.year), int(r.quarter)): r for _, r in df.iterrows()}

    # Compute YoY for each row where prior-year same quarter exists
    yoy_rows = []
    for _, row in df.iterrows():
        yr, qtr = int(row.year), int(row.quarter)
        prior = lkp.get((yr - 1, qtr))
        if prior is None:
            continue

        # EPS YoY — handle zero/negative base carefully
        eps_base = prior.eps
        if eps_base == 0:
            continue  # undefined growth
        eps_yoy = (row.eps - eps_base) / abs(eps_base) * 100

        # Revenue YoY
        rev_base = prior.revenue
        if rev_base == 0 or not np.isfinite(rev_base):
            continue
        rev_yoy = (row.revenue - rev_base) / abs(rev_base) * 100

        yoy_rows.append({
            "year":    yr,
            "quarter": qtr,
            "eps_yoy": eps_yoy,
            "rev_yoy": rev_yoy,
            "npm":     row.npm,
        })

    if len(yoy_rows) < 3:
        return None

    yoy_df = (pd.DataFrame(yoy_rows)
                .sort_values(["year", "quarter"])
                .reset_index(drop=True))

    # Scan for ANY 3 consecutive quarters that qualify
    # "Consecutive" = the (year, quarter) sequence must be adjacent calendar quarters
    def is_next_quarter(r1, r2) -> bool:
        """True if r2 is exactly 1 quarter after r1."""
        yr1, q1 = int(r1.year), int(r1.quarter)
        yr2, q2 = int(r2.year), int(r2.quarter)
        if q1 < 4:
            return yr2 == yr1 and q2 == q1 + 1
        else:
            return yr2 == yr1 + 1 and q2 == 1

    # Walk through sorted yoy_df, find consecutive triplets
    qualifying_windows = []
    for i in range(len(yoy_df) - 2):
        q1 = yoy_df.iloc[i]
        q2 = yoy_df.iloc[i + 1]
        q3 = yoy_df.iloc[i + 2]

        # Must be truly consecutive quarters
        if not (is_next_quarter(q1, q2) and is_next_quarter(q2, q3)):
            continue

        # NaN check
        needed = ["eps_yoy", "rev_yoy", "npm"]
        if any(not np.isfinite(float(q[c])) for q in [q1, q2, q3] for c in needed):
            continue

        eps_accel = (q2.eps_yoy > q1.eps_yoy) and (q3.eps_yoy > q2.eps_yoy)
        rev_accel = (q2.rev_yoy > q1.rev_yoy) and (q3.rev_yoy > q2.rev_yoy)
        npm_expand = (q2.npm > q1.npm)         and (q3.npm > q2.npm)

        if eps_accel and rev_accel and npm_expand:
            # Recency filter: the window's last quarter must be recent enough
            end_yr, end_qtr = int(q3.year), int(q3.quarter)
            if (end_yr, end_qtr) >= (min_end_year, min_end_quarter):
                qualifying_windows.append((q1, q2, q3))

    if not qualifying_windows:
        return None

    # Return the most recent qualifying window
    q1, q2, q3 = qualifying_windows[-1]

    def qname(r) -> str:
        return f"Q{int(r.quarter)}{int(r.year)}"

    return {
        "Qualifying Period":     f"{qname(q1)}->{qname(q3)}",
        "Window End (Yr/Qtr)":   f"{int(q3.year)}-Q{int(q3.quarter)}",
        "EPS YoY Trend (%)":     f"{q1.eps_yoy:.1f} -> {q2.eps_yoy:.1f} -> {q3.eps_yoy:.1f}",
        "Rev YoY Trend (%)":     f"{q1.rev_yoy:.1f} -> {q2.rev_yoy:.1f} -> {q3.rev_yoy:.1f}",
        "Net Margin Trend (%)":  f"{q1.npm*100:.2f} -> {q2.npm*100:.2f} -> {q3.npm*100:.2f}",
        "Latest EPS YoY":        round(q3.eps_yoy, 1),
        "Latest Rev YoY":        round(q3.rev_yoy, 1),
        "Latest NPM (%)":        round(q3.npm * 100, 2),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  CODE 33 SCREENER - Minervini Fundamental Signal")
    print(f"  Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    # Load CSV
    df_csv = pd.read_csv(CSV_PATH)
    tickers  = df_csv["Symbol"].dropna().str.strip().tolist()
    name_map = dict(zip(df_csv["Symbol"].str.strip(), df_csv["Description"]))
    print(f"\nLoaded {len(tickers)} tickers from CSV.\n")

    results  = []
    failed   = []   # insufficient data or errors
    no_qual  = []   # fetched OK but doesn't meet Code 33

    start = time.time()

    for i, symbol in enumerate(tickers, 1):
        source = None

        # ── 1. Finnhub primary ──
        df_fin = get_finnhub_quarterly(symbol)
        if df_fin is not None:
            source = "Finnhub"
        else:
            # ── 2. yfinance fallback ──
            df_fin = get_yfinance_quarterly(symbol)
            if df_fin is not None:
                source = "yfinance"

        # Progress every 50 tickers
        if i % 50 == 0:
            elapsed  = time.time() - start
            rate     = elapsed / i
            remaining = rate * (len(tickers) - i)
            print(f"  [{i:>3}/{len(tickers)}] | Qualifiers: {len(results):>3} | "
                  f"ETA: {remaining/60:.1f} min")

        if df_fin is None:
            failed.append(symbol)
            continue

        result = compute_code33(df_fin)

        if result is None:
            no_qual.append(symbol)
            continue

        company = name_map.get(symbol, "")
        row = {
            "Ticker":  symbol,
            "Company": company,
            "Source":  source,
            **result,
        }
        results.append(row)
        print(f"  [+] {symbol:<8} {company[:35]:<35} | {result['Qualifying Period']} | "
              f"EPS:{result['Latest EPS YoY']:>7.1f}% "
              f"Rev:{result['Latest Rev YoY']:>7.1f}% "
              f"NPM:{result['Latest NPM (%)']:>6.2f}%")

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    print("\n" + "=" * 65)
    print(f"  COMPLETE in {elapsed/60:.1f} min")
    print(f"  Screened:          {len(tickers)}")
    print(f"  Code 33 qualified: {len(results)}")
    print(f"  No signal:         {len(no_qual)}")
    print(f"  Insufficient data: {len(failed)}")
    print("=" * 65)

    if not results:
        print("\nNo stocks qualified for Code 33.")
        return

    # ── Save CSV ─────────────────────────────────────────────────────────────
    out_df = pd.DataFrame(results)
    col_order = [
        "Ticker", "Company", "Source",
        "Qualifying Period", "Window End (Yr/Qtr)",
        "EPS YoY Trend (%)", "Rev YoY Trend (%)", "Net Margin Trend (%)",
        "Latest EPS YoY", "Latest Rev YoY", "Latest NPM (%)",
    ]
    out_df = out_df[col_order]
    out_df = out_df.sort_values("Latest EPS YoY", ascending=False)

    out_df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nResults saved: {OUTPUT_PATH}\n")

    # ── Print table ───────────────────────────────────────────────────────────
    print("\n=== CODE 33 QUALIFYING STOCKS ===\n")
    pd.set_option("display.max_colwidth", 35)
    pd.set_option("display.width", 200)
    print(out_df[["Ticker", "Company", "Qualifying Period", "Window End (Yr/Qtr)",
                   "EPS YoY Trend (%)", "Rev YoY Trend (%)",
                   "Net Margin Trend (%)"]].to_string(index=False))

    # Failed tickers (for reference)
    if failed:
        print(f"\nTickers with insufficient data ({len(failed)}):")
        print(", ".join(failed))


if __name__ == "__main__":
    main()
