import os
import sys
import csv
import random
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'

import streamlit as st
st.cache_data = lambda *a,**kw:(lambda f:f)

from utils.code33_engine import get_code33_data
from utils.sec_edgar import get_cik

CSV_FILE = r"C:\Users\Meet Singh\quant-terminal\Minervini_builder_Managed_2026-04-28.csv"
OUT_FILE = r"C:\Users\Meet Singh\quant-terminal\tools\revenue_accuracy_audit.txt"
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
    if not cik:
        return None
    try:
        time.sleep(0.1)
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        facts = r.json()
    except Exception:
        return None
    
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    dedup = {}
    
    for concept in CONCEPTS:
        entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
        for e in entries:
            form = str(e.get('form', '')).strip().upper()
            if form not in ('10-Q', '10-K', '20-F', '6-K'):
                continue
            if not e.get('end') or not e.get('start'):
                continue
            try:
                start_dt = datetime.strptime(e['start'], '%Y-%m-%d').date()
                end_dt = datetime.strptime(e['end'], '%Y-%m-%d').date()
                dur = (end_dt - start_dt).days
            except Exception:
                continue
            
            if 75 <= dur <= 105:
                key = e['end']
                filed_s = str(e.get('filed', '')).strip()
                try:
                    filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else datetime.min.date()
                except Exception:
                    filed_dt = datetime.min.date()
                
                cloned = {'end': key, 'end_dt': end_dt, 'val': float(e['val']), 'filed': filed_dt}
                if key not in dedup:
                    dedup[key] = cloned
                else:
                    if filed_dt > dedup[key]['filed']:
                        dedup[key] = cloned

    if not dedup:
        return None
        
    entries_sorted = sorted(dedup.values(), key=lambda x: x['end_dt'], reverse=True)
    return entries_sorted

def calc_edgar_yoy(entries):
    yoy_map = {}
    for curr in entries:
        curr_dt = curr['end_dt']
        try:
            target_dt = curr_dt.replace(year=curr_dt.year - 1)
        except ValueError:
            target_dt = curr_dt - timedelta(days=365)
            
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
            yoy_map[curr['end']] = rate
            
    return yoy_map

def audit_ticker(ticker):
    try:
        data = get_code33_data(ticker)
        
        if not data.get('is_us'):
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'Not US stock'}
            
        engine_yoy = data.get('rev_yoy', [])
        engine_ends = data.get('rev_end_dates', [])
        
        if not engine_yoy or not engine_ends:
            return {'ticker': ticker, 'status': 'INSUFFICIENT', 'msg': 'Engine returned no Rev YoY', 'diffs': []}
            
        edgar_entries = fetch_edgar_revenue(ticker)
        if not edgar_entries:
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'No EDGAR data', 'diffs': []}
            
        edgar_yoy_map = calc_edgar_yoy(edgar_entries)
        
        diffs = []
        for eng_rate, eng_end in zip(engine_yoy, engine_ends):
            if eng_rate is None:
                continue
            
            try:
                eng_dt = datetime.strptime(eng_end, '%Y-%m-%d').date()
            except Exception:
                continue
                
            best_diff = 61
            edgar_match_end = None
            for e_end in edgar_yoy_map.keys():
                try:
                    e_dt = datetime.strptime(e_end, '%Y-%m-%d').date()
                except Exception:
                    continue
                diff = abs((e_dt - eng_dt).days)
                if diff < best_diff:
                    best_diff = diff
                    edgar_match_end = e_end
                    
            if edgar_match_end:
                edgar_rate = edgar_yoy_map[edgar_match_end]
                abs_diff = abs(eng_rate - edgar_rate)
                diffs.append(abs_diff)

        if not diffs:
            return {'ticker': ticker, 'status': 'INSUFFICIENT', 'msg': 'No matching quarters in EDGAR', 'diffs': []}
            
        max_diff = max(diffs)
        avg_diff = sum(diffs) / len(diffs)
        status = 'MATCH' if max_diff < 2.0 else 'MISMATCH'
        
        return {
            'ticker': ticker,
            'status': status,
            'max_diff': max_diff,
            'avg_diff': avg_diff,
            'q_count': len(diffs)
        }
        
    except Exception as e:
        return {'ticker': ticker, 'status': 'ERROR', 'msg': str(e), 'diffs': []}

def main():
    if not os.path.exists(CSV_FILE):
        print(f"CSV not found: {CSV_FILE}")
        return
        
    tickers = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Symbol'):
                tickers.append(row['Symbol'].strip())
                
    random.seed(123)
    sample = random.sample(tickers, min(100, len(tickers)))
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(audit_ticker, t): t for t in sample}
        for future in as_completed(futures):
            try:
                res = future.result(timeout=15)
                results.append(res)
            except Exception as e:
                t = futures[future]
                results.append({'ticker': t, 'status': 'ERROR', 'msg': f"Timeout or Exception: {e}"})
            
    stats = {'MATCH': 0, 'MISMATCH': 0, 'INSUFFICIENT': 0, 'ERROR': 0}
    total_diff = 0
    diff_count = 0
    
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write("=== REVENUE ACCURACY AUDIT ===\n\n")
        for r in sorted(results, key=lambda x: x['status']):
            status = r['status']
            stats[status] += 1
            if status in ('MATCH', 'MISMATCH'):
                f.write(f"{r['ticker']:<6} | {status:<10} | Qs: {r.get('q_count', 0)} | Max Diff: {r.get('max_diff', 0):.2f}%\n")
                total_diff += r.get('avg_diff', 0) * r.get('q_count', 1)
                diff_count += r.get('q_count', 1)
            else:
                f.write(f"{r['ticker']:<6} | {status:<10} | {r.get('msg', '')}\n")
    
    total = len(sample)
    matched = stats['MATCH']
    mismatched = stats['MISMATCH']
    match_pct = (matched / (matched + mismatched)) * 100 if (matched + mismatched) > 0 else 0
    mismatch_pct = (mismatched / (matched + mismatched)) * 100 if (matched + mismatched) > 0 else 0
    avg_diff = total_diff / diff_count if diff_count > 0 else 0
    
    summary = f"""
Summary:
- Total tickers tested: {total}
- MATCH count: {matched} ({match_pct:.1f}%)
- MISMATCH count: {mismatched} ({mismatch_pct:.1f}%)
- INSUFFICIENT count: {stats['INSUFFICIENT']}
- ERROR count: {stats['ERROR']}
- Average abs diff %: {avg_diff:.2f}%
"""
    print(summary.strip())
    
    with open(OUT_FILE, 'a', encoding='utf-8') as f:
        f.write("\n" + summary.strip())

if __name__ == "__main__":
    main()
