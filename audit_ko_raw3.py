import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

facts = get_edgar_facts('KO')
usgaap = facts.get('facts', {}).get('us-gaap', {})
units = usgaap.get('SalesRevenueGoodsNet', {}).get('units', {}).get('USD', [])

entries = []
for e in units:
    end_s = str(e.get('end', '')).strip()
    val = e.get('val')
    entries.append({'end': end_s, 'val': val})

entries.sort(key=lambda x: x['end'])
print("Raw SalesRevenueGoodsNet most recent 10 entries:")
for e in entries[-10:]:
    print(f"  {e['end']}: {e['val']}")
