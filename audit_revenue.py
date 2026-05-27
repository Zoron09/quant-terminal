import sys
from datetime import datetime, timedelta
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

rev_keys_edgar = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet',
    'RevenueFromContractWithCustomer'
]

tickers = ['KO', 'XOM']

for ticker in tickers:
    print(f"\n{'='*40}\nAUDIT FOR {ticker}\n{'='*40}")
    facts = get_edgar_facts(ticker)
    if not facts:
        print("No EDGAR facts found.")
        continue
    
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    # 3. What other revenue concepts exist
    print("--- Available Revenue/Sales Concepts ---")
    available_rev_concepts = []
    for concept_name, concept_data in usgaap.items():
        if 'revenue' in concept_name.lower() or 'sales' in concept_name.lower():
            units = concept_data.get('units', {})
            count = 0
            for unit, entries in units.items():
                count += len(entries)
            available_rev_concepts.append((concept_name, count))
    
    available_rev_concepts.sort(key=lambda x: x[1], reverse=True)
    for c, count in available_rev_concepts:
        print(f"  {c}: {count} entries")

    # Simulate _edgar_metric logic to see which is selected
    cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()
    
    selected_concept = None
    selected_results = []
    
    for concept in rev_keys_edgar:
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
            # Keep highest value if multiple (simplified deduplication for audit)
            if end_s not in by_end or float(val) > by_end[end_s]['_val']:
                by_end[end_s] = entry
        
        results = list(by_end.values())
        if len(results) >= 4:
            selected_concept = concept
            selected_results = sorted(results, key=lambda x: x['_end_dt'])
            break
            
    print("\n--- Selected Concept ---")
    if selected_concept:
        print(f"Selected: {selected_concept}")
        print("Raw values per quarter (last 8):")
        for r in selected_results[-8:]:
            print(f"  {r['_end_dt']}: {r['_val']:,.0f}")
    else:
        print("None of the predefined concepts yielded >= 4 quarters of data.")
