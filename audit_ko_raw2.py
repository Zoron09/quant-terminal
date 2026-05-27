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
    entries.append({'end': end_s, 'val': float(val), 'dur': dur, 'form': e.get('form')})

entries.sort(key=lambda x: x['end'])
print("Raw SalesRevenueGoodsNet recent 20 entries:")
for e in entries[-20:]:
    print(f"  {e['end']} (dur {e['dur']}): {e['val']:,.0f} (form {e['form']})")
