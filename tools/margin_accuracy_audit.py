import os
import sys
import csv
import random
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'

import streamlit as st
st.cache_data = lambda *a,**kw:(lambda f:f)

from utils.code33_engine import get_code33_data
from utils.sec_edgar import get_cik

CSV_FILE = r"C:\Users\Meet Singh\quant-terminal\Minervini_builder_Managed_2026-04-28.csv"
OUT_FILE = r"C:\Users\Meet Singh\quant-terminal\tools\margin_accuracy_audit.txt"
EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}
REV_CONCEPTS = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet'
]
NI_CONCEPTS = [
    'NetIncomeLoss',
    'NetIncome',
    'ProfitLoss',
    'NetIncomeLossAvailableToCommonStockholdersBasic'
]

def get_fy_end_month(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        if 'lastFiscalYearEnd' in info:
            fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
            m = fy_end_dt.month
            return 12 if m == 1 else m
    except Exception:
        pass
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
    except Exception:
        return ""

def _extract_metric(usgaap, concepts):
    dedup = {}
    for concept in concepts:
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
    return dedup

def fetch_edgar_margin(ticker):
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
    
    rev_dedup = _extract_metric(usgaap, REV_CONCEPTS)
    ni_dedup = _extract_metric(usgaap, NI_CONCEPTS)
    
    if not rev_dedup or not ni_dedup:
        return None
        
    margin_map = {}
    for rev_end, rev_entry in rev_dedup.items():
        if rev_entry['val'] == 0:
            continue
            
        best_ni = None
        for ni_end, ni_entry in ni_dedup.items():
            diff = abs((rev_entry['end_dt'] - ni_entry['end_dt']).days)
            if diff <= 60:
                best_ni = ni_entry
                break
                
        if best_ni:
            margin = (best_ni['val'] / rev_entry['val']) * 100
            margin_map[rev_end] = {'end_dt': rev_entry['end_dt'], 'margin': margin}
            
    return margin_map

def audit_ticker(ticker):
    try:
        data = get_code33_data(ticker)
        
        if not data.get('is_us'):
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'Not US stock'}
            
        engine_npm = data.get('npm', [])
        engine_labels = data.get('npm_labels', [])
        
        if not engine_npm or not engine_labels:
            return {'ticker': ticker, 'status': 'INSUFFICIENT', 'msg': 'Engine returned no NPM', 'diffs': []}
            
        edgar_margin_map = fetch_edgar_margin(ticker)
        if not edgar_margin_map:
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'No EDGAR data', 'diffs': []}
            
        fy_end_m = get_fy_end_month(ticker)
        edgar_label_map = {}
        for e_end, e_data in edgar_margin_map.items():
            edgar_label_map[e_end] = _get_fq_fy(e_data['end_dt'], fy_end_m)
        
        diffs = []
        for eng_val, eng_label in zip(engine_npm, engine_labels):
            if eng_val is None:
                continue
                
            edgar_match_end = None
            for e_end in edgar_margin_map.keys():
                if edgar_label_map[e_end] == eng_label:
                    edgar_match_end = e_end
                    break
                    
            if edgar_match_end:
                edgar_val = edgar_margin_map[edgar_match_end]['margin']
                abs_diff = abs(eng_val - edgar_val)
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
                
    random.seed(456)
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
        f.write("=== MARGIN ACCURACY AUDIT ===\n\n")
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
