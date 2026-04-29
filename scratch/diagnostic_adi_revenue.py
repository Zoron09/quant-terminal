import requests
from datetime import datetime

cik = '0000006281'
facts = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
usgaap = facts['facts'].get('us-gaap', {})
concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'
entries = usgaap[concept].get('units', {}).get('USD', [])

seen = {}
for e in entries:
    if e.get('form') in ('10-Q','10-K') and e.get('start'):
        start = datetime.strptime(e['start'], '%Y-%m-%d')
        end = datetime.strptime(e['end'], '%Y-%m-%d')
        dur = (end-start).days
        if 75 <= dur <= 105:
            key = e['end']
            if key not in seen:
                seen[key] = e

for k in sorted(seen.keys()):
    e = seen[k]
    print(f'end={e["end"]} val=${e["val"]/1e9:.3f}B filed={e["filed"]}')
