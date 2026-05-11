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

from utils.code33_engine import get_code33_data, _c33_status
from utils.sec_edgar import get_cik
from tools.margin_accuracy_audit import _extract_metric, _get_fq_fy, get_fy_end_month, is_financial_sector, EDGAR_UA, REV_CONCEPTS, NI_CONCEPTS

CSV_FILE = r"C:\Users\Meet Singh\quant-terminal\Minervini_builder_Managed_2026-04-28.csv"
OUT_FILE = r"C:\Users\Meet Singh\quant-terminal\tools\code33_full_audit.txt"

SHARE_CONCEPTS = [
    'WeightedAverageNumberOfDilutedSharesOutstanding',
    'WeightedAverageNumberOfSharesOutstandingBasic'
]

def fetch_edgar_full(ticker):
    cik = get_cik(ticker)
    if not cik: return None
    try:
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        facts = r.json()
    except Exception:
        return None
        
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    def _extract_shares(usgaap, concepts):
        dedup = {}
        for concept in concepts:
            entries = usgaap.get(concept, {}).get('units', {}).get('shares', [])
            for e in entries:
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
                    cloned = {'end': key, 'end_dt': end_dt, 'val': float(e['val'])}
                    dedup[key] = cloned
        return dedup

    rev_dedup = _extract_metric(usgaap, REV_CONCEPTS, is_revenue=True)
    ni_dedup = _extract_metric(usgaap, NI_CONCEPTS)
    shares_dedup = _extract_shares(usgaap, SHARE_CONCEPTS)
    
    results = {}
    
    for end_dt_str, rev_entry in rev_dedup.items():
        results[end_dt_str] = {'end_dt': rev_entry['end_dt'], 'rev': rev_entry['val'], 'ni': None, 'shares': None, 'eps': None, 'margin': None}
        
    for end_dt_str, ni_entry in ni_dedup.items():
        if end_dt_str not in results:
            results[end_dt_str] = {'end_dt': ni_entry['end_dt'], 'rev': None, 'ni': ni_entry['val'], 'shares': None, 'eps': None, 'margin': None}
        else:
            results[end_dt_str]['ni'] = ni_entry['val']
            
    for end_dt_str, sh_entry in shares_dedup.items():
        if end_dt_str in results:
            results[end_dt_str]['shares'] = sh_entry['val']
            
    for end_dt_str, data in results.items():
        if data['ni'] is not None and data['rev'] and data['rev'] != 0:
            if data['rev'] >= 0.10 * abs(data['ni']):
                data['margin'] = (data['ni'] / data['rev']) * 100
        if data['ni'] is not None and data['shares'] and data['shares'] != 0:
            data['eps'] = data['ni'] / data['shares']
            
    for end_dt_str, data in results.items():
        data['rev_yoy'] = None
        data['eps_yoy'] = None
        
        target_dt = data['end_dt'] - timedelta(days=365)
        prior = None
        for p_dt_str, p_data in results.items():
            if abs((p_data['end_dt'] - target_dt).days) <= 25:
                prior = p_data
                break
                
        if prior:
            if data['rev'] is not None and prior['rev'] and prior['rev'] > 0:
                data['rev_yoy'] = ((data['rev'] - prior['rev']) / abs(prior['rev'])) * 100
            if data['eps'] is not None and prior['eps'] is not None and prior['eps'] > 0:
                data['eps_yoy'] = ((data['eps'] - prior['eps']) / abs(prior['eps'])) * 100
                
    return results

def audit_ticker(ticker):
    try:
        if is_financial_sector(ticker):
            return {'ticker': ticker, 'status': 'SECTOR_EXCLUDED', 'msg': 'Bank/Financial excluded'}
            
        data = get_code33_data(ticker)
        if not data.get('is_us'):
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'Not US stock'}
            
        status_sig = _c33_status(data.get('eps_yoy', []))[0].upper()
            
        eng_eps = data.get('eps_yoy', [])
        eng_rev = data.get('rev_yoy', [])
        eng_npm = data.get('npm', [])
        eps_labels = data.get('eps_labels', [])
        rev_labels = data.get('rev_labels', [])
        npm_labels = data.get('npm_labels', [])
            
        if not eps_labels and not rev_labels and not npm_labels:
            return {'ticker': ticker, 'status': 'INSUFFICIENT', 'msg': 'No engine labels'}
            
        edgar_ref = fetch_edgar_full(ticker)
        if not edgar_ref:
            return {'ticker': ticker, 'status': 'ERROR', 'msg': 'No EDGAR data'}
            
        fy_m = get_fy_end_month(ticker)
        edgar_label_map = {}
        for e_end, e_data in edgar_ref.items():
            edgar_label_map[_get_fq_fy(e_data['end_dt'], fy_m)] = e_data
            
        eps_diffs = []
        rev_diffs = []
        npm_diffs = []
        
        for i, lbl in enumerate(eps_labels):
            e_v = eng_eps[i] if i < len(eng_eps) else None
            if e_v is not None and lbl in edgar_label_map:
                ref_v = edgar_label_map[lbl].get('eps_yoy')
                if ref_v is not None:
                    eps_diffs.append(abs(e_v - ref_v))
                    
        for i, lbl in enumerate(rev_labels):
            e_v = eng_rev[i] if i < len(eng_rev) else None
            if e_v is not None and lbl in edgar_label_map:
                ref_v = edgar_label_map[lbl].get('rev_yoy')
                if ref_v is not None:
                    rev_diffs.append(abs(e_v - ref_v))
                    
        for i, lbl in enumerate(npm_labels):
            e_v = eng_npm[i] if i < len(eng_npm) else None
            if e_v is not None and lbl in edgar_label_map:
                ref_v = edgar_label_map[lbl].get('margin')
                if ref_v is not None:
                    npm_diffs.append(abs(e_v - ref_v))

        def process_metric(diffs):
            if not diffs: return {'match': False, 'avg_diff': 0, 'has_data': False}
            m_diff = max(diffs)
            return {'match': m_diff < 2.0, 'avg_diff': sum(diffs)/len(diffs), 'has_data': True}
            
        e_res = process_metric(eps_diffs)
        r_res = process_metric(rev_diffs)
        n_res = process_metric(npm_diffs)
        
        return {
            'ticker': ticker,
            'status': 'OK',
            'eps': e_res,
            'rev': r_res,
            'npm': n_res,
            'signal': status_sig
        }
    except Exception as e:
        return {'ticker': ticker, 'status': 'ERROR', 'msg': str(e)}

def main():
    tickers = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Symbol'): tickers.append(row['Symbol'].strip())
            
    random.seed(789)
    sample = random.sample(tickers, min(100, len(tickers)))
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(audit_ticker, t): t for t in sample}
        for future in as_completed(futures):
            try:
                results.append(future.result(timeout=15))
            except Exception as e:
                results.append({'ticker': futures[future], 'status': 'ERROR', 'msg': str(e)})

    stats = {'Total': len(sample), 'EPS_Match': 0, 'EPS_Has': 0, 'Rev_Match': 0, 'Rev_Has': 0, 'NPM_Match': 0, 'NPM_Has': 0, 'ALL_Match': 0}
    eps_d = 0; rev_d = 0; npm_d = 0
    signals = {}
    
    with open(OUT_FILE, 'w') as f:
        f.write("=== CODE 33 FULL AUDIT ===\n\n")
        for r in results:
            if r['status'] == 'OK':
                em = "MATCH" if r['eps']['match'] else "MISMATCH"
                rm = "MATCH" if r['rev']['match'] else "MISMATCH"
                nm = "MATCH" if r['npm']['match'] else "MISMATCH"
                if not r['eps']['has_data']: em = "N/A"
                if not r['rev']['has_data']: rm = "N/A"
                if not r['npm']['has_data']: nm = "N/A"
                
                f.write(f"{r['ticker']:<6} | EPS: {em:<8} | REV: {rm:<8} | NPM: {nm:<8} | Sig: {r['signal']}\n")
                
                if r['eps']['has_data']:
                    stats['EPS_Has'] += 1
                    eps_d += r['eps']['avg_diff']
                    if r['eps']['match']: stats['EPS_Match'] += 1
                if r['rev']['has_data']:
                    stats['Rev_Has'] += 1
                    rev_d += r['rev']['avg_diff']
                    if r['rev']['match']: stats['Rev_Match'] += 1
                if r['npm']['has_data']:
                    stats['NPM_Has'] += 1
                    npm_d += r['npm']['avg_diff']
                    if r['npm']['match']: stats['NPM_Match'] += 1
                    
                if r['eps']['match'] and r['rev']['match'] and r['npm']['match']:
                    stats['ALL_Match'] += 1
                    
                sig = r['signal']
                signals[sig] = signals.get(sig, 0) + 1
            else:
                f.write(f"{r['ticker']:<6} | {r['status']} | {r.get('msg','')}\n")

    summary = f"\nSummary:\n- Total tickers tested: {stats['Total']}\n"
    if stats['EPS_Has']: summary += f"- EPS: MATCH {stats['EPS_Match']}/{stats['EPS_Has']} ({(stats['EPS_Match']/stats['EPS_Has'])*100:.1f}%) | Avg Diff: {eps_d/stats['EPS_Has']:.2f}%\n"
    if stats['Rev_Has']: summary += f"- Revenue: MATCH {stats['Rev_Match']}/{stats['Rev_Has']} ({(stats['Rev_Match']/stats['Rev_Has'])*100:.1f}%) | Avg Diff: {rev_d/stats['Rev_Has']:.2f}%\n"
    if stats['NPM_Has']: summary += f"- Net Margin: MATCH {stats['NPM_Match']}/{stats['NPM_Has']} ({(stats['NPM_Match']/stats['NPM_Has'])*100:.1f}%) | Avg Diff: {npm_d/stats['NPM_Has']:.2f}%\n"
    summary += f"- Overall ALL THREE Match: {stats['ALL_Match']}\n"
    summary += f"- Signal distribution: {signals}\n"
    
    print(summary.strip())
    with open(OUT_FILE, 'a') as f:
        f.write("\n" + summary.strip())

if __name__ == '__main__':
    main()
