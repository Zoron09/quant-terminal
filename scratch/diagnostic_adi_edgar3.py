import requests
from datetime import datetime

cik = '0000006281'
facts = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
usgaap = facts['facts'].get('us-gaap', {})

concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'
entries = usgaap[concept].get('units', {}).get('USD', [])
print(f'All standalone quarterly entries for {concept}:')
for e in entries:
    if e.get('form') in ('10-Q','10-K') and e.get('start'):
        start = datetime.strptime(e['start'], '%Y-%m-%d')
        end = datetime.strptime(e['end'], '%Y-%m-%d')
        dur = (end-start).days
        if 75 <= dur <= 105 and end.year >= 2023:
            print(f'  start={e["start"]} end={e["end"]} val={e["val"]:,} form={e["form"]} filed={e["filed"]}')
