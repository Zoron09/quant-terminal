import os
import sys
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'
import streamlit as st; st.cache_data = lambda *a,**kw:(lambda f:f)

from utils.code33_engine import get_code33_data
from utils.sec_edgar import get_cik

EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}
CONCEPTS = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet'
]

def fetch_edgar_revenue(ticker):
    cik = get_cik(ticker)
    if not cik: return None
    try:
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers=EDGAR_UA, timeout=10)
        r.raise_for_status()
        facts = r.json()
    except: return None
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    dedup = {}
    for concept in CONCEPTS:
        for e in usgaap.get(concept, {}).get('units', {}).get('USD', []):
            form = str(e.get('form', '')).strip().upper()
            if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
            if not e.get('end') or not e.get('start'): continue
            try:
                start_dt = datetime.strptime(e['start'], '%Y-%m-%d').date()
                end_dt = datetime.strptime(e['end'], '%Y-%m-%d').date()
                dur = (end_dt - start_dt).days
            except: continue
            if 75 <= dur <= 105:
                key = e['end']
                filed_s = str(e.get('filed', '')).strip()
                filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else datetime.min.date()
                cloned = {'end': key, 'end_dt': end_dt, 'val': float(e['val']), 'filed': filed_dt}
                if key not in dedup or filed_dt > dedup[key]['filed']:
                    dedup[key] = cloned
    return sorted(dedup.values(), key=lambda x: x['end_dt'], reverse=True)

def calc_edgar_yoy(entries):
    yoy_map = {}
    for curr in entries:
        curr_dt = curr['end_dt']
        try: target_dt = curr_dt.replace(year=curr_dt.year - 1)
        except ValueError: target_dt = curr_dt - timedelta(days=365)
        best_diff = 61
        best_prior = None
        for prior in entries:
            if prior['end'] == curr['end']: continue
            diff = abs((prior['end_dt'] - target_dt).days)
            if diff < best_diff:
                best_diff = diff; best_prior = prior
        if best_prior and best_prior['val'] != 0:
            yoy_map[curr['end']] = (curr['val'] - best_prior['val']) / abs(best_prior['val']) * 100
    return yoy_map

tickers = ['ECG', 'CGNX', 'LXU', 'HUN', 'STT', 'HPE', 'RNG', 'OLN', 'IESC', 'LNTH']
for t in tickers:
    print(f"--- {t} ---")
    try:
        data = get_code33_data(t)
        eng_yoy = data.get('rev_yoy', [])
        eng_lbls = data.get('rev_labels', [])
        eng_ends = data.get('rev_end_dates', [])
        
        edgar_entries = fetch_edgar_revenue(t)
        edgar_yoy_map = calc_edgar_yoy(edgar_entries) if edgar_entries else {}
        
        for rate, lbl, eng_end in zip(eng_yoy, eng_lbls, eng_ends):
            if rate is None: continue
            try: eng_dt = datetime.strptime(eng_end, '%Y-%m-%d').date()
            except: continue
            best_diff = 61
            edgar_match = None
            for e_end in edgar_yoy_map.keys():
                e_dt = datetime.strptime(e_end, '%Y-%m-%d').date()
                diff = abs((e_dt - eng_dt).days)
                if diff < best_diff:
                    best_diff = diff; edgar_match = e_end
            if edgar_match:
                e_rate = edgar_yoy_map[edgar_match]
                diff_val = abs(rate - e_rate)
                print(f"Ticker: {t} | Q: {lbl} | Terminal: {rate:8.2f}% | EDGAR: {e_rate:8.2f}% | Diff: {diff_val:6.2f}%")
            else:
                print(f"Ticker: {t} | Q: {lbl} | Terminal: {rate:8.2f}% | EDGAR: NO MATCH | Diff: N/A")
    except Exception as e:
        print(f"Error processing {t}: {e}")
