import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()

def extract_q(usgaap, concept):
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

for ticker, targets in [('XOM', {'2025-09-30': -0.0429, '2025-12-31': -0.0181, '2026-03-31': 0.0731}), 
                        ('KO', {'2025-09-26': 0.0567, '2025-12-31': 0.0566, '2026-04-03': 0.1275})]:
    print(f"\n======================================")
    print(f"SEARCHING COMBINATIONS: {ticker}")
    print(f"======================================")
    facts = get_edgar_facts(ticker)
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    # Pre-extract all concept values
    all_q_data = {}
    for concept in usgaap.keys():
        data = extract_q(usgaap, concept)
        if data:
            all_q_data[concept] = {k: v['_val'] for k, v in data.items()}
            
    for q_dt_str, tv_yoy in targets.items():
        q_dt = datetime.strptime(q_dt_str, '%Y-%m-%d')
        p_dt = q_dt - timedelta(days=365)
        
        print(f"\n--- Target: {q_dt_str} (TV YoY: {tv_yoy*100:+.2f}%) ---")
        
        # Check single concepts
        for c, d in all_q_data.items():
            # find value near q_dt
            v_curr = None
            for k, v in d.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - q_dt).days) <= 15: v_curr = v; break
            v_prior = None
            for k, v in d.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - p_dt).days) <= 15: v_prior = v; break
                
            if v_curr and v_prior and v_prior != 0:
                yoy = (v_curr / v_prior) - 1
                if abs(yoy - tv_yoy) < 0.001:
                    print(f"  Exact Match Single Concept: {c} ({yoy*100:+.2f}%) (Vals: {v_curr:,.0f} / {v_prior:,.0f})")
                    
        # Check additions (C1 + C2)
        if ticker == 'XOM' and 'Revenues' in all_q_data:
            c1 = 'Revenues'
            d1 = all_q_data[c1]
            v1_curr = None
            for k, v in d1.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - q_dt).days) <= 15: v1_curr = v; break
            v1_prior = None
            for k, v in d1.items():
                if abs((datetime.strptime(k, '%Y-%m-%d') - p_dt).days) <= 15: v1_prior = v; break
                
            if v1_curr and v1_prior:
                for c2, d2 in all_q_data.items():
                    if c2 == c1: continue
                    v2_curr = None
                    for k, v in d2.items():
                        if abs((datetime.strptime(k, '%Y-%m-%d') - q_dt).days) <= 15: v2_curr = v; break
                    v2_prior = None
                    for k, v in d2.items():
                        if abs((datetime.strptime(k, '%Y-%m-%d') - p_dt).days) <= 15: v2_prior = v; break
                        
                    if v2_curr and v2_prior:
                        # Addition
                        comb_curr = v1_curr + v2_curr
                        comb_prior = v1_prior + v2_prior
                        yoy_add = (comb_curr / comb_prior) - 1
                        if abs(yoy_add - tv_yoy) < 0.001:
                            print(f"  Match Add: {c1} + {c2} ({yoy_add*100:+.2f}%)")
                        
                        # Subtraction
                        comb_curr = v1_curr - v2_curr
                        comb_prior = v1_prior - v2_prior
                        if comb_prior != 0:
                            yoy_sub = (comb_curr / comb_prior) - 1
                            if abs(yoy_sub - tv_yoy) < 0.001:
                                print(f"  Match Sub: {c1} - {c2} ({yoy_sub*100:+.2f}%)")

