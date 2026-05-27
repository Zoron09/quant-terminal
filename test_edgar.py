import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

print("Checking LLY vs AXON EDGAR data for NetIncomeLoss")

for ticker in ['LLY', 'AXON']:
    print(f"\n--- {ticker} ---")
    facts = get_edgar_facts(ticker)
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    entries = usgaap.get('NetIncomeLoss', {}).get('units', {}).get('USD', [])
    # Let's filter for the last 2 years 
    q4_entries = []
    annual_entries = []
    
    for e in entries:
        try:
            end = e.get('end', '')
            if end > '2023-01-01':
                form = e.get('form', '')
                fp = str(e.get('fp', ''))
                dur = (sys.modules['datetime'].datetime.strptime(end, '%Y-%m-%d') - 
                       sys.modules['datetime'].datetime.strptime(e['start'], '%Y-%m-%d')).days
                if form == '10-K' and 75 <= dur <= 105:
                    q4_entries.append((end, dur, form, e['val']))
                if form == '10-K' and dur > 350:
                    annual_entries.append((end, dur, form, e['val']))
        except Exception:
            pass
            
    print(f"Discrete Q4 entries in 10-K (75-105 days): {len(q4_entries)}")
    if q4_entries:
        print("  Sample:", q4_entries[0])
    print(f"Annual entries in 10-K (>350 days): {len(annual_entries)}")
    if annual_entries:
        print("  Sample:", annual_entries[0])
