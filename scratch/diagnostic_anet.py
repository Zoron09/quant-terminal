import sys
import os
import yfinance as yf
from datetime import datetime, timedelta

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.code33_engine import get_edgar_facts, _get_fq_fy

def _sf(v):
    import numpy as np
    if v is None: return None
    try: 
        f = float(v)
        return None if np.isnan(f) else f
    except: return None

def get_anet_edgar():
    ticker = 'ANET'
    fy_end_month = 12
    
    facts = get_edgar_facts(ticker)
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    
    cutoff_date = (datetime.utcnow() - timedelta(days=365 * 5)).date()
    recency_cutoff = (datetime.utcnow() - timedelta(days=548)).date()
    
    global_dedup = {}
    global_ytd_6m = {}
    global_ytd_9m = {}
    global_annual = {}
    
    eps_keys_edgar = ['EarningsPerShareDiluted', 'EarningsPerShareBasic']
    unit = 'USD/shares'
    
    for concept in eps_keys_edgar:
        entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
        if not entries: continue
        for e in entries:
            form = str(e.get('form', '')).strip().upper()
            if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
            end_str = str(e.get('end', '')).strip()
            start_str = str(e.get('start', '')).strip()
            filed_str = str(e.get('filed', '')).strip()
            val = _sf(e.get('val'))
            if not end_str or not start_str or val is None: continue
            
            try:
                end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
            except: continue
            
            if end_dt < cutoff_date: continue
            
            try: filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date() if filed_str else None
            except: filed_dt = None
            
            duration_days = (end_dt - start_dt).days
            end_key = e['end']
            
            cloned = dict(e)
            cloned['_end_dt'] = end_dt
            cloned['_filed_dt'] = filed_dt
            cloned['_val'] = float(val)
            cloned['_fy'] = int(e['fy']) if e.get('fy') is not None else end_dt.year
            cloned['_fp'] = str(e['fp']).strip().upper() if e.get('fp') else None
            cloned['form'] = form
            
            if 80 <= duration_days <= 105:
                if end_key not in global_dedup:
                    global_dedup[end_key] = cloned
                elif filed_dt and global_dedup[end_key]['_filed_dt'] and filed_dt > global_dedup[end_key]['_filed_dt']:
                    global_dedup[end_key] = cloned
            elif 170 <= duration_days <= 195:
                if end_key not in global_ytd_6m:
                    global_ytd_6m[end_key] = cloned
                elif filed_dt and global_ytd_6m[end_key]['_filed_dt'] and filed_dt > global_ytd_6m[end_key]['_filed_dt']:
                    global_ytd_6m[end_key] = cloned
            elif 260 <= duration_days <= 285:
                if end_key not in global_ytd_9m:
                    global_ytd_9m[end_key] = cloned
                elif filed_dt and global_ytd_9m[end_key]['_filed_dt'] and filed_dt > global_ytd_9m[end_key]['_filed_dt']:
                    global_ytd_9m[end_key] = cloned
            elif 350 <= duration_days <= 380:
                if form in ('10-K', '20-F'):
                    annual_fy = int(e['fy']) if e.get('fy') is not None else None
                    f_dt = filed_dt if filed_dt else datetime.min.date()
                    if end_dt not in global_annual or f_dt > global_annual[end_dt][4]:
                        global_annual[end_dt] = (end_dt, start_dt, float(val), annual_fy, f_dt)
                        
    for ytd_end, ytd_entry in global_ytd_6m.items():
        if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):
            target_q1_end = ytd_entry['_end_dt'] - timedelta(days=90)
            q1_entry = next((v for v in global_dedup.values() if abs((v['_end_dt'] - target_q1_end).days) <= 25), None)
            if q1_entry:
                derived_q2 = dict(ytd_entry)
                derived_q2['_val'] = ytd_entry['_val'] - q1_entry['_val']
                derived_q2['form'] = '10-Q-derived'
                global_dedup[ytd_end] = derived_q2

    for ytd_end, ytd_entry in global_ytd_9m.items():
        if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):
            target_q2_end = ytd_entry['_end_dt'] - timedelta(days=90)
            ytd_6m_entry = next((v for v in global_ytd_6m.values() if abs((v['_end_dt'] - target_q2_end).days) <= 25), None)
            if ytd_6m_entry:
                derived_q3 = dict(ytd_entry)
                derived_q3['_val'] = ytd_entry['_val'] - ytd_6m_entry['_val']
                derived_q3['form'] = '10-Q-derived'
                global_dedup[ytd_end] = derived_q3

    filtered_entries = sorted(global_dedup.values(), key=lambda x: x['_end_dt'], reverse=True)
    filtered_entries = filtered_entries[:8]
    filtered_entries.reverse()

    annual_entries = [(item[0], item[1], item[2], item[3]) for item in global_annual.values()]
    existing_ends = {item['_end_dt'] for item in filtered_entries}
    for annual_end, annual_start, annual_val, annual_fy in annual_entries:
        already_exists = any(abs((annual_end - existing_end).days) <= 45 for existing_end in existing_ends)
        if already_exists: continue
        q_in_year = [item for item in global_dedup.values() if item['_end_dt'] > annual_start and item['_end_dt'] <= annual_end]
        if len(q_in_year) == 3:
            q4_val = annual_val - sum(item['_val'] for item in q_in_year)
            derived = {
                '_end_dt': annual_end,
                '_filed_dt': None,
                '_val': q4_val,
                'form': '10-K-derived',
                '_fy': q_in_year[0]['_fy'],
                '_fp': 'Q4',
            }
            filtered_entries.append(derived)
            existing_ends.add(annual_end)

    filtered_entries.sort(key=lambda x: x['_end_dt'])
    
    vals = [item['_val'] for item in filtered_entries]
    ends = [item['_end_dt'].isoformat() for item in filtered_entries]
    lbls = [_get_fq_fy(item['_end_dt'], fy_end_month) for item in filtered_entries]
    fys = [item.get('_fy') for item in filtered_entries]
    fps = [item.get('_fp') for item in filtered_entries]
    
    return vals, ends, fys, fps

def run():
    print("--- RAW EDGAR EPS POOL BEFORE YOY ---")
    vals, ends, fys, fps = get_anet_edgar()
    
    pool = []
    for v, e, fy, fp in zip(vals or [], ends or [], fys or [None]*len(vals or []), fps or [None]*len(vals or [])):
        if v is not None and e:
            pool.append({'val': float(v), 'end': e, 'fy': fy, 'fp': str(fp).strip().upper() if fp else None})
            
    pool.sort(key=lambda x: x['end'], reverse=True)
    
    deduped = []
    for entry in pool:
        duplicate = False
        for kept in deduped:
            try:
                d1 = datetime.strptime(entry['end'], '%Y-%m-%d').date()
                d2 = datetime.strptime(kept['end'],  '%Y-%m-%d').date()
                if abs((d1 - d2).days) <= 45:
                    duplicate = True
                    break
            except Exception:
                pass
        if not duplicate:
            deduped.append(entry)
            
    for item in deduped:
        print(f"period_end: {item['end']:<10} | fy: {str(item['fy']):<4} | fp: {str(item['fp']):<4} | val: {item['val']:.3f}")
        
    print("\n--- ACTUAL YOY PAIRS ---")
    results = []
    seen = set()
    
    for i, curr in enumerate(deduped):
        if curr['end'] in seen: continue
        try: curr_dt = datetime.strptime(curr['end'], '%Y-%m-%d').date()
        except: continue
        
        # Find prior
        prior = None
        if curr['fy'] is not None and curr['fp'] in ('Q1', 'Q2', 'Q3', 'Q4'):
            target_fy = curr['fy'] - 1
            for cand in deduped:
                if cand['end'] == curr['end']: continue
                if cand['fy'] == target_fy and cand['fp'] == curr['fp']:
                    prior = cand
                    break
                    
        if prior is None:
            try: target_dt = curr_dt.replace(year=curr_dt.year - 1)
            except ValueError: target_dt = curr_dt - timedelta(days=365)
            best_diff = 32
            best_cand = None
            for cand in deduped:
                if cand['end'] == curr['end']: continue
                try:
                    cand_dt = datetime.strptime(cand['end'], '%Y-%m-%d').date()
                    diff = abs((cand_dt - target_dt).days)
                    if diff < best_diff:
                        best_diff = diff
                        best_cand = cand
                except: pass
            if best_cand is not None:
                prior = best_cand
                
        if prior is None:
            if i + 4 < len(deduped):
                seq_prior = deduped[i + 4]
                try:
                    sq_dt = datetime.strptime(seq_prior['end'], '%Y-%m-%d').date()
                    diff_months = (curr_dt - sq_dt).days / 30.4
                    if 9 <= diff_months <= 15:
                        prior = seq_prior
                except: pass
                
        if prior is None or prior['val'] == 0:
            print(f"curr_end: {curr['end']:<10} | curr_val: {curr['val']:>6.3f} | No prior found")
            continue
            
        seen.add(curr['end'])
        rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100
        print(f"curr_end: {curr['end']:<10} | curr_val: {curr['val']:>6.3f} | prior_end: {prior['end']:<10} | prior_val: {prior['val']:>6.3f} | calculated_rate: {rate:+.1f}%")

if __name__ == "__main__":
    run()
