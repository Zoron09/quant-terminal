import os, sys, requests, traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
FMP_KEY = os.getenv('FMP_API_KEY', '')

TICKERS = ["TSLA", "PLTR", "META", "ORCL", "AMZN", "NFLX", "AXON", "CELH", "MELI", "ALAB", "AAPL", "UBER", "TTD", "DUOL", "HOOD", "RKLB", "HIMS", "CRWD", "SHOP", "APP"]

HDR = {'User-Agent': 'quant-terminal meet@example.com', 'Accept': 'application/json'}

def _sf(v):
    try: return float(v)
    except: return None

def get_fmp(ticker):
    try:
        r = requests.get(f'https://financialmodelingprep.com/api/v3/income-statement/{ticker}',
                         params={'period': 'quarter', 'limit': 12, 'apikey': FMP_KEY},
                         timeout=10, headers=HDR)
        r.raise_for_status()
        return r.json()
    except:
        return []

def get_edgar(ticker):
    try:
        tl = requests.get('https://www.sec.gov/files/company_tickers.json', timeout=10, headers=HDR)
        tl.raise_for_status()
        cik = None
        for entry in tl.json().values():
            if entry.get('ticker', '').upper() == ticker.upper():
                cik = str(entry['cik_str']).zfill(10)
                break
        if not cik: return []
        
        facts_r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', timeout=10, headers=HDR)
        facts_r.raise_for_status()
        usgaap = facts_r.json().get('facts', {}).get('us-gaap', {})
        
        # Rev
        rev_entries = []
        for c in ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Revenues', 'SalesRevenueNet']:
            e = usgaap.get(c, {}).get('units', {}).get('USD', [])
            if e:
                rev_entries = e
                break
                
        ni_entries = []
        for c in ['NetIncomeLoss', 'NetIncome', 'ProfitLoss']:
            e = usgaap.get(c, {}).get('units', {}).get('USD', [])
            if e:
                ni_entries = e
                break
                
        return rev_entries, ni_entries
    except:
        return [], []

def synthesize_q4(entries):
    annual = []
    qrt = []
    for e in entries:
        form = str(e.get('form', '')).upper()
        if not e.get('end') or not e.get('start') or e.get('val') is None: continue
        try:
            end_dt = datetime.strptime(e['end'], '%Y-%m-%d').date()
            start_dt = datetime.strptime(e['start'], '%Y-%m-%d').date()
        except: continue
        dur = (end_dt - start_dt).days
        if form == '10-K' and 350 <= dur <= 380:
            annual.append((end_dt, start_dt, _sf(e['val'])))
        elif form == '10-Q' and 80 <= dur <= 105:
            qrt.append((end_dt, start_dt, _sf(e['val'])))
            
    # simplified representation
    res = {q[0]: q[2] for q in qrt}
    return res

results = {}

for t in TICKERS:
    fmp = get_fmp(t)
    fmp_rev_map = {e['date']: e.get('revenue') for e in fmp if e.get('date')}
    fmp_ni_map = {e['date']: e.get('netIncome') for e in fmp if e.get('date')}
    
    # We will simulate missing data
    fmp_has_rev = sum(1 for v in fmp_rev_map.values() if v is not None)
    fmp_has_ni = sum(1 for v in fmp_ni_map.values() if v is not None)
    
    # Do we have mismatches in FMP?
    mismatches = 0
    all_dates = set(fmp_rev_map.keys()).union(set(fmp_ni_map.keys()))
    for d in all_dates:
        r = fmp_rev_map.get(d)
        n = fmp_ni_map.get(d)
        if (r is None and n is not None) or (r is not None and n is None):
            mismatches += 1
            
    # if mismatches > 0, the source lock will drop those.
    print(f"{t}: FMP Rev {fmp_has_rev}, FMP NI {fmp_has_ni}, Mismatched dates: {mismatches}")

