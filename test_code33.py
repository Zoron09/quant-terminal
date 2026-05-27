import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data, get_edgar_facts

print("OK - Syntax check passed.")

for ticker in ['EDRY', 'AXON', 'ANET']:
    print(f"\n--- {ticker} ---")
    data = get_code33_data(ticker)
    
    rev_yoy = data.get('rev_yoy', [])
    rev_lbl = data.get('rev_labels', [])
    
    if ticker == 'EDRY':
        print("Raw quarters found per concept for EDRY (Revenue):")
        facts = get_edgar_facts(ticker)
        usgaap = facts.get('facts', {}).get('us-gaap', {}) if facts else {}
        rev_keys = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'RevenueFromContractWithCustomer']
        for concept in rev_keys:
            entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
            print(f"  {concept}: {len(entries)} entries")
            
        print("\nFinal Revenue YoY%:")
        for lbl, yoy in zip(rev_lbl, rev_yoy):
            print(f"  {lbl}: {yoy:.2f}%" if yoy is not None else f"  {lbl}: None")
            
        npm_yoy = data.get('npm', [])
        npm_lbl = data.get('npm_labels', [])
        print("\nFinal Net Profit Margin (replaces NI YoY):")
        for lbl, yoy in zip(npm_lbl, npm_yoy):
            print(f"  {lbl}: {yoy:.2f}%" if yoy is not None else f"  {lbl}: None")
    else:
        print("Final Revenue YoY%:")
        for lbl, yoy in zip(rev_lbl, rev_yoy):
            print(f"  {lbl}: {yoy:.2f}%" if yoy is not None else f"  {lbl}: None")
