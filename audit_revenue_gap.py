import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

tickers = {
    'XOM': {
        'Q3 2025': {'dt': '2025-09-30', 'yoy': -0.0429},
        'Q4 2025': {'dt': '2025-12-31', 'yoy': -0.0181},
        'Q1 2026': {'dt': '2026-03-31', 'yoy': 0.0731},
    },
    'KO': {
        'Q3 2025': {'dt': '2025-09-26', 'yoy': 0.0567},
        'Q4 2025': {'dt': '2025-12-31', 'yoy': 0.0566}, # KO uses derived Q4 for 12-31
        'Q1 2026': {'dt': '2026-04-03', 'yoy': 0.1275},
    }
}

cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()

for ticker, targets in tickers.items():
    print(f"\n======================================")
    print(f"AUDITING {ticker}")
    print(f"======================================")
    facts = get_edgar_facts(ticker)
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    rev_concepts = {}
    
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
        return sorted(list(by_end.values()), key=lambda x: x['_end_dt'])

    def extract_annual(concept):
        units = usgaap.get(concept, {}).get('units', {}).get('USD', [])
        by_end = {}
        for e in units:
            form = str(e.get('form', '')).upper()
            if form not in ('10-K', '20-F'): continue
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
            if not (335 <= dur <= 395): continue
            
            if end_s not in by_end or float(val) > by_end[end_s]:
                by_end[end_s] = float(val)
        return by_end

    print("\n--- 1. All available XBRL revenue-related concepts ---")
    for concept_name in usgaap.keys():
        if 'revenue' in concept_name.lower() or 'sales' in concept_name.lower():
            q_data = extract_q(concept_name)
            if q_data:
                rev_concepts[concept_name] = {r['_end_dt'].strftime('%Y-%m-%d'): r['_val'] for r in q_data}
                
                # Derive Q4 if applicable
                a_data = extract_annual(concept_name)
                for a_end_s, a_val in a_data.items():
                    a_dt = datetime.strptime(a_end_s, '%Y-%m-%d')
                    q_in_year = [r for r in q_data if r['_end_dt'] > a_dt.date() - timedelta(days=365) and r['_end_dt'] <= a_dt.date()]
                    if len(q_in_year) == 3:
                        q4_val = a_val - sum(r['_val'] for r in q_in_year)
                        if a_end_s not in rev_concepts[concept_name]:
                            rev_concepts[concept_name][a_end_s] = q4_val

                recent = sorted(rev_concepts[concept_name].keys())[-4:]
                print(f"  {concept_name}:")
                for d in recent:
                    print(f"    {d}: {rev_concepts[concept_name][d]:,.0f}")
                    
    print("\n--- 2. TV Back-calculated vs Engine (Revenues) ---")
    engine_concept = 'Revenues'
    if engine_concept not in rev_concepts:
        print(f"{engine_concept} not found!")
        continue
        
    engine_data = rev_concepts[engine_concept]
    
    for q_label, tv_info in targets.items():
        q_dt = tv_info['dt']
        tv_yoy = tv_info['yoy']
        
        # find matching quarter and prior year quarter
        target_val = None
        prior_val = None
        
        # allow slight drift
        def get_val(dt_str, data_dict):
            t_dt = datetime.strptime(dt_str, '%Y-%m-%d')
            best = None
            best_diff = 999
            for k, v in data_dict.items():
                k_dt = datetime.strptime(k, '%Y-%m-%d')
                diff = abs((k_dt - t_dt).days)
                if diff <= 45 and diff < best_diff:
                    best = v
                    best_diff = diff
            return best
            
        target_val = get_val(q_dt, engine_data)
        
        # prior year
        p_dt = datetime.strptime(q_dt, '%Y-%m-%d') - timedelta(days=365)
        prior_val = get_val(p_dt.strftime('%Y-%m-%d'), engine_data)
        
        if prior_val:
            tv_target_raw = prior_val * (1 + tv_yoy)
            eng_yoy = (target_val / prior_val - 1) if target_val else 0
            print(f"  {q_label} (Target {q_dt}):")
            print(f"    Prior Year:   {prior_val:,.0f}")
            print(f"    TV YoY:       {tv_yoy*100:+.2f}% -> Implied TV Raw: {tv_target_raw:,.0f}")
            print(f"    Engine Raw:   {target_val:,.0f} -> Engine YoY: {eng_yoy*100:+.2f}%")
            print(f"    Raw Diff:     {target_val - tv_target_raw:,.0f}")
            
            # Check combinations
            print(f"    --- Concept Combinations ---")
            for c1, d1 in rev_concepts.items():
                v1 = get_val(q_dt, d1)
                p1 = get_val(p_dt.strftime('%Y-%m-%d'), d1)
                if v1 and p1:
                    y1 = (v1 / p1 - 1)
                    if abs(y1 - tv_yoy) < 0.001:
                        print(f"    Exact match found! {c1}")
            
            # What if it's Revenues - ExciseTaxes?
            if 'ExciseAndSalesTaxes' in rev_concepts:
                v_tax = get_val(q_dt, rev_concepts['ExciseAndSalesTaxes'])
                p_tax = get_val(p_dt.strftime('%Y-%m-%d'), rev_concepts['ExciseAndSalesTaxes'])
                if target_val and prior_val and v_tax and p_tax:
                    adj_v = target_val - v_tax
                    adj_p = prior_val - p_tax
                    adj_yoy = (adj_v / adj_p - 1)
                    print(f"    Revenues - ExciseAndSalesTaxes YoY: {adj_yoy*100:+.2f}% (Raw: {adj_v:,.0f})")

