import sys
from datetime import datetime
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_edgar_facts

facts = get_edgar_facts('AXON')
entries = facts.get('facts', {}).get('us-gaap', {}).get('NetIncomeLoss', {}).get('units', {}).get('USD', [])

for e in entries:
    if e.get('end') == '2024-12-31':
        start_dt = datetime.strptime(e['start'], '%Y-%m-%d')
        end_dt = datetime.strptime(e['end'], '%Y-%m-%d')
        print(f"End: {e['end']}, Start: {e['start']}, Duration: {(end_dt - start_dt).days}, Val: {e['val']}, Form: {e.get('form')}")
