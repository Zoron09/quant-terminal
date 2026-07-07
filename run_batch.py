import sys, csv, time, threading
sys.stdout.reconfigure(encoding='utf-8')
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

sys.path.insert(0, r'C:\Users\Meet Singh\quant-terminal')
from utils.code33_engine import get_code33_data

CSV_IN  = r'C:\Users\Meet Singh\Downloads\Minervini builder Managed copy_2026-06-27.csv'
CSV_OUT = r'C:\Users\Meet Singh\quant-terminal\code33_results_2026-06-27.csv'

tickers = []
with open(CSV_IN, newline='', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        t = (row.get('Ticker') or row.get('Symbol') or row.get('ticker') or '').strip()
        if t: tickers.append(t)

print(f"Loaded {len(tickers)} tickers", flush=True)

results = []
lock = threading.Lock()
done = [0]

def scan_one(t):
    try:
        data = get_code33_data(t)
        status = data.get('status', 'INSUFFICIENT')
    except:
        status = 'INSUFFICIENT'
        data = {}
    with lock:
        done[0] += 1
        if done[0] % 10 == 0:
            print(f"[{done[0]}/{len(tickers)}]", flush=True)
        if status.upper() in ('ACTIVE','GREEN','YELLOW'):
            print(f"✅ {t} — {status} — {data.get('company_name','')}", flush=True)
    return {'ticker':t,'status':status,'company':data.get('company_name',''),'sector':data.get('sector','')}

print("Scanning with 10 threads...", flush=True)
start = time.time()
with ThreadPoolExecutor(max_workers=10) as ex:
    for f in as_completed({ex.submit(scan_one,t):t for t in tickers}):
        results.append(f.result())

with open(CSV_OUT,'w',newline='',encoding='utf-8') as f:
    w = csv.DictWriter(f,fieldnames=['ticker','status','company','sector'])
    w.writeheader(); w.writerows(results)

print(f"\nDone in {int(time.time()-start)}s", flush=True)
counts = Counter(r['status'] for r in results)
for k,v in sorted(counts.items()): print(f"  {k}: {v}")

print("\n🟢 GREEN/ACTIVE:")
for r in sorted(results,key=lambda x:x['ticker']):
    if r['status'].upper() in ('ACTIVE','GREEN'):
        print(f"  {r['ticker']:<8} {r['company']:<35} {r['sector']}")

print("\n🟡 YELLOW:")
for r in sorted(results,key=lambda x:x['ticker']):
    if r['status'].upper() == 'YELLOW':
        print(f"  {r['ticker']:<8} {r['company']:<35} {r['sector']}")
