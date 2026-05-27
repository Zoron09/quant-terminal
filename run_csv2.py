import csv
import concurrent.futures
from utils.code33_engine import get_code33_data
import time
import sys

input_file = r"C:\Users\Meet Singh\Downloads\Minervini builder Managed_2026-05-25.csv"
output_file = r"C:\Users\Meet Singh\quant-terminal\Code33_Results_2026-05-25.csv"

tickers = []
with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Symbol' in row:
            tickers.append(row['Symbol'].strip())

print(f"Loaded {len(tickers)} tickers from CSV.", flush=True)

results = []
summary = {'green': 0, 'yellow': 0, 'red': 0, 'insufficient': 0, 'crash': 0}

def process_ticker(t):
    try:
        d = get_code33_data(t, 1)
        s = d.get('status', 'insufficient')
        if isinstance(s, list): s = s[0] if s else 'insufficient'
        return {'Ticker': t, 'Status': s, 'EPS_Source': d.get('sources', {}).get('eps', 'none')}
    except Exception as e:
        return {'Ticker': t, 'Status': 'crash', 'EPS_Source': str(e)}

start = time.time()
# Use max_workers=2 to prevent yfinance SQLite/socket deadlocks on Windows
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = {executor.submit(process_ticker, t): t for t in tickers}
    processed = 0
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Ticker', 'Status', 'EPS_Source'])
        writer.writeheader()
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            writer.writerow(res)
            f.flush()
            summary[res['Status']] = summary.get(res['Status'], 0) + 1
            processed += 1
            if processed % 10 == 0:
                print(f"Processed {processed}/{len(tickers)}", flush=True)

print(f"Done in {time.time()-start:.1f}s", flush=True)
print(f"Summary: {summary}", flush=True)
print(f"Saved to {output_file}", flush=True)
