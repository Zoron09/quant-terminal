import sys, os, requests
sys.path.insert(0, '.')

# Get ADI CIK
r = requests.get('https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK=ADI&type=10-Q&dateb=&owner=include&count=10&search_text=&output=atom', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'})

# Direct CIK lookup
tickers = requests.get('https://www.sec.gov/files/company_tickers.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
adi_cik = None
for k,v in tickers.items():
    if v['ticker'] == 'ADI':
        adi_cik = str(v['cik_str']).zfill(10)
        break
print('ADI CIK:', adi_cik)

# Get revenue from EDGAR
facts = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{adi_cik}.json', headers={'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}).json()
revenues = facts['facts']['us-gaap'].get('Revenues', facts['facts']['us-gaap'].get('RevenueFromContractWithCustomerExcludingAssessedTax', {}))
entries = revenues.get('units', {}).get('USD', [])
standalone = [e for e in entries if e.get('form') in ('10-Q','10-K') and e.get('start') and 75 <= (len(e['end']) - len(e['start'])) <= 0]

# Print standalone quarterly entries after 2023
from datetime import datetime
for e in entries:
    if e.get('form') in ('10-Q','10-K') and e.get('start'):
        start = datetime.strptime(e['start'], '%Y-%m-%d')
        end = datetime.strptime(e['end'], '%Y-%m-%d')
        dur = (end-start).days
        if 75 <= dur <= 105 and end.year >= 2023:
            print(f'start={e["start"]} end={e["end"]} val={e["val"]:,} form={e["form"]} filed={e["filed"]} dur={dur}d')
