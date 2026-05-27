import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()

for ticker in ['XOM', 'KO']:
    print(f"\n======================================")
    print(f"AUDITING {ticker} (ALL RECENT CONCEPTS)")
    print(f"======================================")
    facts = get_edgar_facts(ticker)
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    def get_recent_q_val(concept):
        units = usgaap.get(concept, {}).get('units', {}).get('USD', [])
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
            
            # check if end_dt is around Q3 2025 (2025-09-30)
            if '2025-09' in end_s or '2025-12' in end_s or '2026-03' in end_s:
                return True
        return False

    cands = []
    for concept in usgaap.keys():
        if get_recent_q_val(concept):
            cands.append(concept)
    
    print(f"Found {len(cands)} concepts with recent quarterly data.")
    
    # We want to see if any concept matches the Raw Diff
    # For XOM: Q3 2025 Raw Diff = ~860M
    # For KO: Q4 2025 Raw Diff = ~375M
    
    def extract_q(concept):
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
        return by_end

    if ticker == 'XOM':
        target_diffs = {'2025-09-30': 860313600, '2025-12-31': -392010600, '2026-03-31': 406880300}
    else:
        target_diffs = {'2025-09-26': 71121800, '2025-12-31': 375390400, '2026-04-03': 75947500}
        
    for concept in cands:
        data = extract_q(concept)
        # Check if values are in the ballpark of the diffs
        # TV Raw = Engine Raw + Diff
        for dt, diff in target_diffs.items():
            best_diff = 999
            matched = False
            for k, v in data.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - datetime.strptime(dt, '%Y-%m-%d')).days) < 15:
                    if abs(abs(v['_val']) - abs(diff)) < abs(diff) * 0.1: # within 10% of diff
                        print(f"  {concept} matches Diff for {dt}! Value: {v['_val']:,.0f} (Target diff: {diff:,.0f})")
                        matched = True
            
            # Also check if it matches TV Raw exactly
            if ticker == 'XOM':
                tv_raws = {'2025-09-30': 86154313600, '2025-12-31': 81915989400, '2026-03-31': 89206803000}
            else:
                tv_raws = {'2025-09-26': 12526121800, '2025-12-31': 12197390400, '2026-04-03': 12547947500}
            for k, v in data.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - datetime.strptime(dt, '%Y-%m-%d')).days) < 15:
                    if abs(v['_val'] - tv_raws[dt]) < tv_raws[dt] * 0.01:
                        print(f"  {concept} matches TV Raw for {dt}! Value: {v['_val']:,.0f}")
