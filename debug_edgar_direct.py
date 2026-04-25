import os
import sys
import json
import importlib

sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
from utils.sec_edgar import get_cik
stock_detail = importlib.import_module("pages.15_stock_detail")
get_edgar_facts = stock_detail.get_edgar_facts

def debug_edgar(ticker):
    facts = get_edgar_facts(ticker)
    if not facts:
        print(f"{ticker} - No EDGAR facts returned. CIK: {get_cik(ticker)}")
        return
        
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    # Check what keys look like revenue
    possible_rev_keys = [k for k in usgaap.keys() if 'rev' in k.lower() or 'sale' in k.lower()]
    print(f"\n{ticker} - Potential Revenue Keys: {possible_rev_keys}")
    
    # Check Net Income keys
    possible_ni_keys = [k for k in usgaap.keys() if 'netincom' in k.lower() or 'profit' in k.lower()]
    print(f"{ticker} - Potential NI Keys: {possible_ni_keys}")

    # Check the standard keys used in stock_detail
    rev_keys_edgar = ['RevenueFromContractWithCustomerExcludingAssessedTax',
                      'RevenueFromContractWithCustomerIncludingAssessedTax',
                      'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet',
                      'RevenueFromContractWithCustomer']
    
    for concept in rev_keys_edgar:
        entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
        if entries:
            forms = set(e.get('form', '') for e in entries)
            print(f"  Found {concept} with {len(entries)} entries. Forms: {forms}")
            
debug_edgar("ESOA")
debug_edgar("EDRY")
