import re

with open('api/server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Add prints
old_scan = '''    tickers = df['Symbol'].str.upper().tolist() \\
        if 'Symbol' in df.columns else []

    winners = []
    insufficient = 0
    total = len(tickers)

    for ticker in tickers:'''

new_scan = '''    tickers = df['Symbol'].str.upper().tolist() \\
        if 'Symbol' in df.columns else []

    print(f"[SCAN] received file: {file.filename}")
    print(f"[SCAN] tickers parsed: {len(tickers)}")
    print(f"[SCAN] first 5 tickers: {tickers[:5]}")

    winners = []
    insufficient = 0
    total = len(tickers)

    for ticker in tickers:'''

code = code.replace(old_scan, new_scan)

old_ret = '''    return JSONResponse({
        'winners': winners,
        'meta': {'''

new_ret = '''    print(f"[SCAN] winners found: {len(winners)}")
    return JSONResponse({
        'winners': winners,
        'meta': {'''

code = code.replace(old_ret, new_ret)

with open('api/server.py', 'w', encoding='utf-8') as f:
    f.write(code)
