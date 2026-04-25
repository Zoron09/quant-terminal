import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_edgar_facts = stock_detail.get_edgar_facts
_sf = stock_detail._sf
from datetime import datetime, timedelta

def show_edgar_quarterly(ticker, concept):
    facts = get_edgar_facts(ticker)
    if not facts: 
        print(f"No facts for {ticker}")
        return
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
    print(f"\n{ticker} - {concept}: {len(entries)} total entries")
    for e in entries:
        form = str(e.get('form', '')).strip().upper()
        if form not in ('10-Q', '10-K', '20-F', '6-K'):
            continue
        start_str = e.get('start', '')
        end_str = e.get('end', '')
        if not start_str or not end_str: continue
        start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
        dur = (end_dt - start_dt).days
        if dur < 60 or dur > 400: continue  # only quarterly/semi-annual/annual
        print(f"  Form:{form}, Start:{start_str}, End:{end_str}, Dur:{dur}, Val:{e.get('val')}")

show_edgar_quarterly("ESOA", "RevenueFromContractWithCustomerIncludingAssessedTax")
show_edgar_quarterly("EDRY", "RevenueFromContractWithCustomerIncludingAssessedTax")
