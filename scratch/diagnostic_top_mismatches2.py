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
    except Exception: return None
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

def find_engine_pairs(engine_data, end_date):
    rev_vals = engine_data['rev']
    rev_ends = engine_data['rev_end_dates']
    if not rev_vals or not rev_ends: return None, None, None, None
    curr_val = None
    curr_end = None
    
    try: target = datetime.strptime(end_date, '%Y-%m-%d').date()
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
    
    try: target_prior = target.replace(year=target.year - 1)
    except ValueError: target_prior = target - timedelta(days=365)
    
    best_diff_prior = 61
    prior_val = None
    prior_end = None
    for v, e in zip(rev_vals, rev_ends):
        if not e or v == 0: continue
        e_dt = datetime.strptime(e, '%Y-%m-%d').date()
        diff = abs((e_dt - target_prior).days)
        if diff < best_diff_prior:
            best_diff_prior = diff
            prior_val = v
            prior_end = e
            
    return curr_val, prior_val, curr_end, prior_end

def analyze():
    audit_file = r"C:\Users\Meet Singh\quant-terminal\tools\revenue_accuracy_audit.txt"
    import re
    mismatched = []
    with open(audit_file, 'r') as f:
        for line in f:
            if "MISMATCH" in line:
                t = line.split("|")[0].strip()
                match = re.search(r"Max Diff:\s*([\d\.]+)%", line)
                if match:
                    mismatched.append({'ticker': t, 'max_diff': float(match.group(1))})
                
    mismatched.sort(key=lambda x: x['max_diff'], reverse=True)
    top_tickers = [x['ticker'] for x in mismatched[:15]]
    
    all_q_mismatches = []
    
    for t in top_tickers:
        try:
            data = get_code33_data(t)
            eng_yoy = data.get('rev_yoy', [])
            eng_ends = data.get('rev_end_dates', [])
            if not eng_yoy or not eng_ends: continue
            
            edgar_entries = fetch_edgar_revenue(t)
            if not edgar_entries: continue
            edgar_yoy_map = calc_edgar_yoy(edgar_entries)
            
            for eng_rate, eng_end in zip(eng_yoy, eng_ends):
                if eng_rate is None or not eng_end: continue
                
                try: eng_dt = datetime.strptime(eng_end, '%Y-%m-%d').date()
                except Exception: continue
                
                best_diff = 61
                edgar_match_end = None
                for e_end in edgar_yoy_map.keys():
                    e_dt = datetime.strptime(e_end, '%Y-%m-%d').date()
                    diff = abs((e_dt - eng_dt).days)
                    if diff < best_diff:
                        best_diff = diff
                        edgar_match_end = e_end
                        
                if edgar_match_end:
                    edgar_dict = edgar_yoy_map[edgar_match_end]
                    edgar_rate = edgar_dict['rate']
                    abs_diff = abs(eng_rate - edgar_rate)
                    if abs_diff >= 2.0:
                        eng_curr_val, eng_prior_val, eng_curr_end, eng_prior_end = find_engine_pairs(data, eng_end)
                        q_label = eng_end
                        
                        all_q_mismatches.append({
                            'ticker': t,
                            'q': q_label,
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
            pass

    all_q_mismatches.sort(key=lambda x: x['diff'], reverse=True)
    top_15 = all_q_mismatches[:15]
    
    print("\n--- TOP 15 MISMATCH ENTRIES ---")
    for m in top_15:
        print(f"Ticker: {m['ticker']:<5} | Q: {m['q']:<10} | Terminal: {m['eng_rate']:8.2f}% | EDGAR: {m['edgar_rate']:8.2f}% | Diff: {m['diff']:8.2f}%")
        
    cat1, cat2, cat3, cat4 = 0, 0, 0, 0
    for m in all_q_mismatches:
        if m['eng_prior_end'] and m['edgar_prior_end'] and m['eng_prior_end'] != m['edgar_prior_end']:
            cat1 += 1
        elif m['eng_curr_val'] != m['edgar_curr_val'] or m['eng_prior_val'] != m['edgar_prior_val']:
            if m['eng_curr_val'] and m['edgar_curr_val'] and m['eng_curr_val'] > m['edgar_curr_val'] * 1.5:
                cat3 += 1
            else:
                cat2 += 1
        else:
            cat4 += 1
            
    print("\n--- CATEGORIZATION (All Mismatched Quarters in Top 15 Tickers) ---")
    print(f"1. Wrong quarter pairing (prior year doesn't match): {cat1}")
    print(f"2. Wrong revenue concept being used: {cat2}")
    print(f"3. YTD cumulative derivation issue (same as EPS bug): {cat3}")
    print(f"4. Something else: {cat4}")
    
    print("\n--- 5 SPECIFIC EXAMPLES ---")
    for i, m in enumerate(top_15[:5]):
        print(f"{i+1}. [{m['ticker']} {m['q']}] Diff: {m['diff']:.2f}%")
        print(f"  Terminal: curr_val={m['eng_curr_val']}, prior_val={m['eng_prior_val']}, curr_end={m['eng_curr_end']}, prior_end={m['eng_prior_end']}")
        print(f"  EDGAR:    curr_val={m['edgar_curr_val']}, prior_val={m['edgar_prior_val']}, curr_end={m['edgar_curr_end']}, prior_end={m['edgar_prior_end']}")
        print(f"  Concept:  {m['concept']}")
        print()

if __name__ == "__main__":
    analyze()
