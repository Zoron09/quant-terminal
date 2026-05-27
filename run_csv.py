import csv
import concurrent.futures
from utils.code33_engine import get_code33_data
import time
import os

input_file = r"C:\Users\Meet Singh\Downloads\Minervini builder Managed_2026-05-25.csv"
output_file = r"C:\Users\Meet Singh\quant-terminal\Code33_Results_2026-05-25.csv"

tickers = []
with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Symbol' in row:
            tickers.append(row['Symbol'].strip())

print(f"Loaded {len(tickers)} tickers from CSV.")

results = []
summary = {'green': 0, 'yellow': 0, 'red': 0, 'insufficient': 0, 'crash': 0}

def process_ticker(t):
    try:
        d = get_code33_data(t, 1)
        s = d.get('status', 'insufficient')
        # If it's a list (from older engine versions), handle it, but it should be a string
        if isinstance(s, list): s = s[0] if s else 'insufficient'
        return {'Ticker': t, 'Status': s, 'EPS_Source': d.get('sources', {}).get('eps', 'none')}
    except Exception as e:
        return {'Ticker': t, 'Status': 'crash', 'EPS_Source': str(e)}

start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(process_ticker, t): t for t in tickers}
    for i, future in enumerate(concurrent.futures.as_completed(futures)):
        res = future.result()
        results.append(res)
        summary[res['Status']] = summary.get(res['Status'], 0) + 1
        if (i+1) % 50 == 0:
            print(f"Processed {i+1}/{len(tickers)}")

with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['Ticker', 'Status', 'EPS_Source'])
    writer.writeheader()
    writer.writerows(results)

print(f"Done in {time.time()-start:.1f}s")
print(f"Summary: {summary}")
print(f"Saved to {output_file}")
