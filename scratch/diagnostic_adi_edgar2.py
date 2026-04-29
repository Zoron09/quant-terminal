import requests
from datetime import datetime

cik = '0000006281'
facts = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()

usgaap = facts['facts'].get('us-gaap', {})

# Check all common revenue concepts
revenue_concepts = [
    'Revenues',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet',
    'RevenueNet',
    'NetRevenues',
]

for concept in revenue_concepts:
    if concept in usgaap:
        entries = usgaap[concept].get('units', {}).get('USD', [])
        standalone = []
        for e in entries:
            if e.get('form') in ('10-Q','10-K') and e.get('start'):
                start = datetime.strptime(e['start'], '%Y-%m-%d')
                end = datetime.strptime(e['end'], '%Y-%m-%d')
                dur = (end-start).days
                if 75 <= dur <= 105 and end.year >= 2024:
                    standalone.append(e)
        if standalone:
            print(f'CONCEPT: {concept} — {len(standalone)} standalone quarterly entries after 2024')
            for e in standalone[-6:]:
                print(f'  start={e["start"]} end={e["end"]} val={e["val"]:,} form={e["form"]} filed={e["filed"]}')
        else:
            print(f'CONCEPT: {concept} — found but no standalone quarterly entries')
    else:
        print(f'CONCEPT: {concept} — NOT FOUND')
