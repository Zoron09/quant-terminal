import os
import sys
import requests
from datetime import datetime, timedelta, timezone
import yfinance as yf

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

def get_fy_end_month(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        if 'lastFiscalYearEnd' in info:
            fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
            m = fy_end_dt.month
            return 12 if m == 1 else m
    except Exception: pass
    return 12

def _get_fq_fy(dt, fy_end_m=12):
    try:
        shift = 12 - fy_end_m
        shifted_m = dt.month + shift
        if shifted_m > 12:
            fy = dt.year + 1
            shifted_m -= 12
        else:
            fy = dt.year
        fq = (shifted_m + 2) // 3
        return f"Q{fq} {fy}"
    except Exception: return ""

def fetch_edgar_revenue(ticker):
    cik = get_cik(ticker)
    if not cik: return None
    try:
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers=EDGAR_UA, timeout=10)
        r.raise_for_status()
        facts = r.json()
    except Exception: return None
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    dedup = {}
    for concept in CONCEPTS:
        entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
        for e in entries:
            form = str(e.get('form', '')).strip().upper()
            if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
            if not e.get('end') or not e.get('start'): continue
            try:
                start_dt = datetime.strptime(e['start'], '%Y-%m-%d').date()
                end_dt = datetime.strptime(e['end'], '%Y-%m-%d').date()
                dur = (end_dt - start_dt).days
            except Exception: continue
            if 75 <= dur <= 105:
                key = e['end']
                filed_s = str(e.get('filed', '')).strip()
                filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else datetime.min.date()
                cloned = {'end': key, 'end_dt': end_dt, 'val': float(e['val']), 'filed': filed_dt, 'concept': concept}
                if key not in dedup or filed_dt > dedup[key]['filed']:
                    dedup[key] = cloned
    if not dedup: return None
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
                best_diff = diff
                best_prior = prior
        if best_prior and best_prior['val'] != 0:
            rate = (curr['val'] - best_prior['val']) / abs(best_prior['val']) * 100
            yoy_map[curr['end']] = {
                'rate': rate,
                'curr_val': curr['val'],
                'prior_val': best_prior['val'],
                'curr_end': curr['end'],
                'prior_end': best_prior['end'],
                'concept': curr['concept']
            }
    return yoy_map

def find_engine_pairs(engine_data, rate_to_find, end_label, edgar_match_end):
    rev_vals = engine_data['rev']
    rev_ends = engine_data['rev_end_dates']
    if not rev_vals or not rev_ends: return None, None, None, None
    
    curr_val = None
    curr_end = None
    
    try: target = datetime.strptime(edgar_match_end, '%Y-%m-%d').date()
    except Exception: return None, None, None, None
    
    best_diff = 61
    for v, e in zip(rev_vals, rev_ends):
        if not e: continue
        e_dt = datetime.strptime(e, '%Y-%m-%d').date()
        diff = abs((e_dt - target).days)
        if diff < best_diff:
            best_diff = diff
            curr_val = v
            curr_end = e
            
    if curr_val is None: return None, None, None, None
    
    for v, e in zip(rev_vals, rev_ends):
        if v == 0 or not e: continue
        rate = (curr_val - v) / abs(v) * 100
        if abs(rate - rate_to_find) < 0.1:
            return curr_val, v, curr_end, e
    return curr_val, None, curr_end, None

def analyze():
    # Read tickers from audit file
    audit_file = r"C:\Users\Meet Singh\quant-terminal\tools\revenue_accuracy_audit.txt"
    mismatched = []
    with open(audit_file, 'r') as f:
        for line in f:
            if "MISMATCH" in line:
                t = line.split("|")[0].strip()
                mismatched.append(t)
                
    mismatches = []
    for t in mismatched[:30]:  # Just do top 30 to save time
        print(f"Processing {t}...")
        try:
            data = get_code33_data(t)
            eng_yoy = data.get('rev_yoy', [])
            eng_labels = data.get('rev_labels', [])
            if not eng_yoy or not eng_labels: continue
            
            edgar_entries = fetch_edgar_revenue(t)
            if not edgar_entries: continue
            edgar_yoy_map = calc_edgar_yoy(edgar_entries)
            
            fy_end_m = get_fy_end_month(t)
            edgar_label_map = {e['end']: _get_fq_fy(e['end_dt'], fy_end_m) for e in edgar_entries}
            
            for eng_rate, eng_label in zip(eng_yoy, eng_labels):
                if eng_rate is None: continue
                edgar_match_end = None
                for e_end in edgar_yoy_map.keys():
                    if edgar_label_map[e_end] == eng_label:
                        edgar_match_end = e_end
                        break
                if edgar_match_end:
                    edgar_dict = edgar_yoy_map[edgar_match_end]
                    edgar_rate = edgar_dict['rate']
                    abs_diff = abs(eng_rate - edgar_rate)
                    if abs_diff >= 2.0:
                        eng_curr_val, eng_prior_val, eng_curr_end, eng_prior_end = find_engine_pairs(data, eng_rate, eng_label, edgar_match_end)
                        mismatches.append({
                            'ticker': t,
                            'q': eng_label,
                            'eng_rate': eng_rate,
                            'edgar_rate': edgar_rate,
                            'diff': abs_diff,
                            'eng_curr_val': eng_curr_val,
                            'eng_prior_val': eng_prior_val,
                            'eng_curr_end': eng_curr_end,
                            'eng_prior_end': eng_prior_end,
                            'edgar_curr_val': edgar_dict['curr_val'],
                            'edgar_prior_val': edgar_dict['prior_val'],
                            'edgar_curr_end': edgar_dict['curr_end'],
                            'edgar_prior_end': edgar_dict['prior_end'],
                            'concept': edgar_dict['concept']
                        })
        except Exception as e:
            print(f"Error {t}: {e}")

    mismatches.sort(key=lambda x: x['diff'], reverse=True)
    top_15 = mismatches[:15]
    
    print("--- TOP 15 MISMATCH ENTRIES ---")
    for m in top_15:
        print(f"Ticker: {m['ticker']:<5} | Q: {m['q']:<7} | Terminal: {m['eng_rate']:8.2f}% | EDGAR: {m['edgar_rate']:8.2f}% | Diff: {m['diff']:8.2f}%")
        
    print("\n--- CATEGORIZATION (Sampled from Top Mismatches) ---")
    cat1, cat2, cat3, cat4 = 0, 0, 0, 0
    for m in mismatches:
        if m['eng_prior_end'] and m['edgar_prior_end'] and m['eng_prior_end'] != m['edgar_prior_end']:
            cat1 += 1
        elif m['eng_curr_val'] != m['edgar_curr_val']:
            # Likely wrong concept or YTD cumulative
            # Since FMP might use different concept
            cat2 += 1
        else:
            cat4 += 1
            
    print(f"1. Wrong quarter pairing (prior year doesn't match): {cat1}")
    print(f"2. Wrong revenue concept / YTD derivation issue: {cat2}")
    print(f"3. YTD cumulative derivation issue: (Merged with 2 in this basic analysis)")
    print(f"4. Something else: {cat4}")
    
    print("\n--- 5 SPECIFIC EXAMPLES ---")
    for m in top_15[:5]:
        print(f"[{m['ticker']} {m['q']}] Diff: {m['diff']:.2f}%")
        print(f"  Terminal: curr_val={m['eng_curr_val']}, prior_val={m['eng_prior_val']}, curr_end={m['eng_curr_end']}, prior_end={m['eng_prior_end']}")
        print(f"  EDGAR:    curr_val={m['edgar_curr_val']}, prior_val={m['edgar_prior_val']}, curr_end={m['edgar_curr_end']}, prior_end={m['edgar_prior_end']}")
        print(f"  Concept:  {m['concept']}")
        print()

if __name__ == "__main__":
    analyze()
