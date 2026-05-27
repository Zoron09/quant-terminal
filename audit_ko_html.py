import requests
import json
import re
import sys

headers = {'User-Agent': 'Quant Terminal meet.singh@example.com'}

# KO CIK is 21344 -> CIK0000021344
url = "https://data.sec.gov/submissions/CIK0000021344.json"
r = requests.get(url, headers=headers)
if r.status_code != 200:
    print("Failed to fetch submissions")
    sys.exit(1)

data = r.json()
filings = data['filings']['recent']

# Find latest 10-Q
idx = -1
for i, form in enumerate(filings['form']):
    if form == '10-Q':
        idx = i
        break

if idx == -1:
    print("No 10-Q found")
    sys.exit(1)

acc_num = filings['accessionNumber'][idx]
primary_doc = filings['primaryDocument'][idx]

# Remove dashes for the URL
acc_num_no_dash = acc_num.replace('-', '')
report_url = f"https://www.sec.gov/Archives/edgar/data/21344/{acc_num_no_dash}/{primary_doc}"
print(f"Latest 10-Q URL: {report_url}")
