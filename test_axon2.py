import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

def _sf(v):
    if v is None: return None
    try: return float(v)
    except: return None

facts = get_edgar_facts('AXON')
usgaap = facts.get('facts', {}).get('us-gaap', {})
cutoff   = (datetime.utcnow() - timedelta(days=365 * 5)).date()

def _standalone(concepts, unit, use_first_filed=False):
    by_end = {}
    for concept in concepts:
        for e in usgaap.get(concept, {}).get('units', {}).get(unit, []):
            form = str(e.get('form', '')).upper()
            if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
            end_s   = str(e.get('end',   '')).strip()
            start_s = str(e.get('start', '')).strip()
            filed_s = str(e.get('filed', '')).strip()
            val = _sf(e.get('val'))
            if not end_s or not start_s or val is None: continue
            try:
                end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
                filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else None
            except Exception: continue
            if end_dt < cutoff: continue
            if not (75 <= (end_dt - start_dt).days <= 105): continue
            entry = {
                '_end_dt':   end_dt,
                '_start_dt': start_dt,
                '_filed_dt': filed_dt,
                '_val':      float(val),
                '_fy':       int(e['fy']) if e.get('fy') is not None else end_dt.year,
                '_fp':       str(e['fp']).strip().upper() if e.get('fp') else None,
                'form':      form,
            }
            if end_s not in by_end:
                by_end[end_s] = entry
            elif filed_dt and by_end[end_s]['_filed_dt']:
                if use_first_filed:
                    if filed_dt < by_end[end_s]['_filed_dt']: by_end[end_s] = entry
                else:
                    if filed_dt > by_end[end_s]['_filed_dt']: by_end[end_s] = entry
    return by_end

ni_map = _standalone(
    ['NetIncomeLoss', 'NetIncome', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'], 'USD', False)

print("Original NI MAP quarters:")
for k, v in sorted(ni_map.items()):
    if '2024' in k or '2023' in k:
        print(k, v['_val'], v['form'])

def _annual(concepts, unit, use_first_filed=False):
    by_end = {}
    for concept in concepts:
        for e in usgaap.get(concept, {}).get('units', {}).get(unit, []):
            form = str(e.get('form', '')).upper()
            if form not in ('10-K', '20-F'): continue
            end_s   = str(e.get('end',   '')).strip()
            start_s = str(e.get('start', '')).strip()
            filed_s = str(e.get('filed', '')).strip()
            val = _sf(e.get('val'))
            if not end_s or not start_s or val is None: continue
            try:
                end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
                filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else None
            except Exception: continue
            if end_dt < cutoff: continue
            if not (335 <= (end_dt - start_dt).days <= 395): continue
            entry = {
                '_end_dt':   end_dt,
                '_start_dt': start_dt,
                '_filed_dt': filed_dt,
                '_val':      float(val),
                '_fy':       int(e['fy']) if e.get('fy') is not None else end_dt.year,
                '_fp':       str(e['fp']).strip().upper() if e.get('fp') else None,
                'form':      form,
            }
            if end_s not in by_end:
                by_end[end_s] = entry
            elif filed_dt and by_end[end_s]['_filed_dt']:
                if use_first_filed:
                    if filed_dt < by_end[end_s]['_filed_dt']: by_end[end_s] = entry
                else:
                    if filed_dt > by_end[end_s]['_filed_dt']: by_end[end_s] = entry
    return by_end

ni_ann = _annual(['NetIncomeLoss', 'NetIncome', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'], 'USD', False)
print("\nAnnual NI MAP:")
for k, v in sorted(ni_ann.items()):
    if '2024' in k or '2023' in k:
        print(k, v['_val'], v['form'])

for end_s, ni_a in ni_ann.items():
    end_dt = ni_a['_end_dt']
    q_in_year = [q for q in ni_map.values() if q['_end_dt'] > ni_a['_start_dt'] and q['_end_dt'] <= end_dt]
    print(f"\nFor annual end {end_dt}, found {len(q_in_year)} quarters inside:")
    for q in q_in_year:
        print("  ", q['_end_dt'], q['_val'])
    if len(q_in_year) == 3:
        q4_ni = ni_a['_val'] - sum(q['_val'] for q in q_in_year)
        print("   -> Derived Q4 NI:", q4_ni)
