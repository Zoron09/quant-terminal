import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

facts = get_edgar_facts('KO')
usgaap = facts.get('facts', {}).get('us-gaap', {})
cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()

units = usgaap.get('SalesRevenueGoodsNet', {}).get('units', {}).get('USD', [])
entries = []
for e in units:
    form = str(e.get('form', '')).upper()
    if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
    end_s = str(e.get('end', '')).strip()
    start_s = str(e.get('start', '')).strip()
    val = e.get('val')
    if not end_s or not start_s or val is None: continue
    try:
        end_dt = datetime.strptime(end_s, '%Y-%m-%d').date()
        start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
    except: continue
    if end_dt < cutoff: continue
    dur = (end_dt - start_dt).days
    if not (75 <= dur <= 105): continue
    entries.append({'end': end_s, 'val': float(val)})

entries.sort(key=lambda x: x['end'])
print("Raw SalesRevenueGoodsNet recent 12 entries (75-105 duration):")
for e in entries[-12:]:
    print(f"  {e['end']}: {e['val']:,.0f}")
