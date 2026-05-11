import requests
from datetime import datetime

cik_map = requests.get('https://www.sec.gov/files/company_tickers.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
cik = None
for k,v in cik_map.items():
    if v['ticker'] == 'WULF':
        cik = str(v['cik_str']).zfill(10)
        break
print('WULF CIK:', cik)

facts = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
usgaap = facts['facts'].get('us-gaap', {})

concepts = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Revenues', 'SalesRevenueNet']
for concept in concepts:
    if concept in usgaap:
        entries = usgaap[concept].get('units', {}).get('USD', [])
        standalone = []
        for e in entries:
            if e.get('form') in ('10-Q','10-K') and e.get('start'):
                start = datetime.strptime(e['start'], '%Y-%m-%d')
                end = datetime.strptime(e['end'], '%Y-%m-%d')
                dur = (end-start).days
                if 75 <= dur <= 105:
                    standalone.append(e)
        if standalone:
            print(f'{concept}: {len(standalone)} standalone quarterly entries')
            for e in standalone:
                print(f'  end={e["end"]} val={e["val"]:,}')
