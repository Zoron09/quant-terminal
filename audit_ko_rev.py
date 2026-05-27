import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

facts = get_edgar_facts('KO')
usgaap = facts.get('facts', {}).get('us-gaap', {})
cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()

def fetch_concept(concept):
    units = usgaap.get(concept, {}).get('units', {}).get('USD', [])
    by_end = {}
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
        
        entry = {'_end_dt': end_dt, '_val': float(val)}
        if end_s not in by_end or float(val) > by_end[end_s]['_val']:
            by_end[end_s] = entry
    
    return sorted(list(by_end.values()), key=lambda x: x['_end_dt'])

rev_data = fetch_concept('Revenues')
srgn_data = fetch_concept('SalesRevenueGoodsNet')

rev_dict = {r['_end_dt'].strftime('%Y-%m-%d'): r['_val'] for r in rev_data}
srgn_dict = {r['_end_dt'].strftime('%Y-%m-%d'): r['_val'] for r in srgn_data}

all_dates = sorted(list(set(rev_dict.keys()) | set(srgn_dict.keys())))
last_8_dates = all_dates[-12:] # fetch a bit more to calculate YoY

print("Quarter end date | Revenues | SalesRevenueGoodsNet")
print("-" * 65)
for d in last_8_dates[-8:]:
    r_val = f"{rev_dict.get(d, 0):,.0f}" if d in rev_dict else "N/A"
    s_val = f"{srgn_dict.get(d, 0):,.0f}" if d in srgn_dict else "N/A"
    print(f"{d:16} | {r_val:>15} | {s_val:>20}")

# YoY calculations for SalesRevenueGoodsNet
print("\nYoY% for SalesRevenueGoodsNet:")

# Helper for YoY matching: same month, year-1 (allowing slight day drift)
def get_yoy(dt_str):
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d')
        curr = srgn_dict.get(dt_str)
        if curr is None: return "N/A"
        
        # look for prior year
        prev = None
        for k, v in srgn_dict.items():
            k_dt = datetime.strptime(k, '%Y-%m-%d')
            if k_dt.year == dt.year - 1 and abs(k_dt.month - dt.month) <= 1:
                prev = v
                break
        
        if prev is None or prev == 0: return "N/A"
        yoy = (curr / prev) - 1.0
        return f"{yoy*100:.2f}%"
    except:
        return "N/A"

# Q3 2025 is typically Sep 2024 or 2025. Wait, looking at KO data:
# 2024-09-27 -> Q3 2024. Fiscal shifted Q3 2025 is 2024-09-27.
# Wait! KO's fiscal year end is Dec 31.
# So calendar Q3 2024 (2024-09-27) is Q3 2024.
# Let's map exactly based on the dates provided in the previous output:
# 2024-09-27 (Q3 2025?), 2025-03-28, 2025-06-27, 2025-09-26, 2026-04-03
dates_to_calc = {
    'Q3 2025': '2025-09-26', # Based on previous output, 2025-09-26 is Q3
    'Q4 2025': '2025-12-31', # Or whatever is closest to Dec 2025
    'Q1 2026': '2026-04-03'
}

for k, d in dates_to_calc.items():
    # If exact date doesn't exist, find closest in that quarter
    target_dt = datetime.strptime(d, '%Y-%m-%d')
    best_dt_str = None
    best_diff = 999
    for s_dt_str in srgn_dict.keys():
        s_dt = datetime.strptime(s_dt_str, '%Y-%m-%d')
        diff = abs((s_dt - target_dt).days)
        if diff < 45:
            if diff < best_diff:
                best_diff = diff
                best_dt_str = s_dt_str
    
    if best_dt_str:
        yoy = get_yoy(best_dt_str)
        print(f"{k} ({best_dt_str}): {yoy}")
    else:
        print(f"{k} (around {d}): N/A")

