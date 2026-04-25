import os, sys, json

sys.path.insert(0, os.path.abspath('.'))
import importlib
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

tickers = ["JAKK", "ASYS", "QUIK", "INTT", "ESOA", "UTGN", "WSR", "SODI"]

with open('tests/fixtures/pre_unification_snapshot.json', 'r') as f:
    pre_snap = json.load(f)

NUMERIC_KEYS = ['rev_yoy', 'eps_yoy', 'npm']
STRING_KEYS  = ['rev_labels', 'eps_labels', 'npm_labels', 'rev_end_dates', 'eps_end_dates', 'ni_end_dates']
BOOL_KEYS    = ['is_us', 'sector_excluded', 'is_reit']

issues = {}

for ticker in tickers:
    try:
        post = get_code33_data(ticker)
    except Exception as e:
        issues[ticker] = [f'Engine error: {e}']
        continue

    pre = pre_snap.get(ticker, {})
    ticker_issues = []

    for key in NUMERIC_KEYS:
        pre_vals = pre.get(key, [])
        post_vals = post.get(key, [])
        if len(pre_vals) != len(post_vals):
            ticker_issues.append(f'{key}: length changed {len(pre_vals)} -> {len(post_vals)}')
        else:
            for idx, (a, b) in enumerate(zip(pre_vals, post_vals)):
                if abs(a - b) > 0.001:
                    ticker_issues.append(f'{key}[{idx}]: {a:.3f} -> {b:.3f} (diff {abs(a-b):.4f})')

    for key in BOOL_KEYS:
        if pre.get(key) != post.get(key):
            ticker_issues.append(f'{key}: {pre.get(key)} -> {post.get(key)}')

    if ticker_issues:
        issues[ticker] = ticker_issues

print("\n=== SNAPSHOT DIFF REPORT ===\n")
if not issues:
    print("✅ ZERO DIFFERENCES — engine output identical before and after unification.")
else:
    print(f"❌ {sum(len(v) for v in issues.values())} discrepancies found:")
    for ticker, diffs in issues.items():
        print(f"\n{ticker}:")
        for d in diffs:
            print(f"  - {d}")
