import sys
import importlib
from datetime import datetime
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_edgar_facts = stock_detail.get_edgar_facts

facts = get_edgar_facts("EDRY")
usgaap = facts.get('facts', {}).get('us-gaap', {})
entries = usgaap.get('RevenueFromContractWithCustomerIncludingAssessedTax', {}).get('units', {}).get('USD', [])

for e in entries:
    start_str = e.get('start', '')
    end_str = e.get('end', '')
    if not start_str or not end_str: continue
    start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
    duration_days = (end_dt - start_dt).days
    print(f"Form: {e.get('form')}, Start: {start_str}, End: {end_str}, Dur: {duration_days}, Val: {e.get('val')}")
