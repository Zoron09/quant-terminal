import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

def _sf(v):
    if v is None: return None
    try: return float(v)
    except: return None

facts = get_edgar_facts('ANET')
usgaap = facts.get('facts', {}).get('us-gaap', {})
cutoff   = (datetime.utcnow() - timedelta(days=365 * 5)).date()

by_end = {}
for e in usgaap.get('NetIncomeLoss', {}).get('units', {}).get('USD', []):
    form = str(e.get('form', '')).upper()
    if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
    end_s   = str(e.get('end',   '')).strip()
    start_s = str(e.get('start', '')).strip()
    if not end_s or not start_s: continue
    end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
    start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
    dur = (end_dt - start_dt).days
    if end_s >= '2024-12-01':
        print(f"ANET Entry End: {end_s}, Start: {start_s}, Dur: {dur}, Form: {form}, Val: {e.get('val')}")
