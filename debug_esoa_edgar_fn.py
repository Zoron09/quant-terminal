import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
import importlib
stock_detail = importlib.import_module("pages.15_stock_detail")
get_edgar_facts = stock_detail.get_edgar_facts
_sf = stock_detail._sf

def _edgar_metric(ticker, concepts, unit='USD'):
    facts = get_edgar_facts(ticker)
    if not facts: return [], [], [], [], []
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    cutoff_date = (datetime.utcnow() - timedelta(days=365 * 5)).date()
    recency_cutoff = (datetime.utcnow() - timedelta(days=548)).date()

    for concept in concepts:
        entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
        if not entries: continue

        dedup_by_end = {}
        ytd_6m = {}
        ytd_9m = {}
        for e in entries:
            form = str(e.get('form', '')).strip().upper()
            if form not in ('10-Q', '10-K'): continue
            end_str = str(e.get('end', '')).strip()
            start_str = str(e.get('start', '')).strip()
            filed_str = str(e.get('filed', '')).strip()
            val = _sf(e.get('val'))
            if not end_str or not start_str or val is None: continue

            try:
                end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
            except Exception: continue

            if end_dt < cutoff_date: continue

            try: filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date() if filed_str else None
            except Exception: filed_dt = None

            duration_days = (end_dt - start_dt).days
            
            cloned = dict(e)
            cloned['_end_dt'] = end_dt
            cloned['_filed_dt'] = filed_dt
            cloned['_val'] = float(val)
            cloned['_fy'] = int(e['fy']) if e.get('fy') is not None else end_dt.year
            cloned['_fp'] = str(e['fp']).strip().upper() if e.get('fp') else None
            cloned['form'] = form

            if 80 <= duration_days <= 105:
                if end_str not in dedup_by_end or filed_dt > dedup_by_end[end_str]['_filed_dt']:
                    dedup_by_end[end_str] = cloned
            elif 170 <= duration_days <= 195:
                if end_str not in ytd_6m or filed_dt > ytd_6m[end_str]['_filed_dt']:
                    ytd_6m[end_str] = cloned
            elif 260 <= duration_days <= 285:
                if end_str not in ytd_9m or filed_dt > ytd_9m[end_str]['_filed_dt']:
                    ytd_9m[end_str] = cloned

        # Q2 deriving
        for ytd_end, ytd_entry in ytd_6m.items():
            if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in dedup_by_end.values()):
                target_q1_end = ytd_entry['_end_dt'] - timedelta(days=90)
                q1_entry = next((v for v in dedup_by_end.values() if abs((v['_end_dt'] - target_q1_end).days) <= 25), None)
                if q1_entry:
                    derived_q2 = dict(ytd_entry)
                    derived_q2['_val'] = ytd_entry['_val'] - q1_entry['_val']
                    derived_q2['form'] = '10-Q-derived'
                    dedup_by_end[ytd_end] = derived_q2

        # Q3 deriving
        for ytd_end, ytd_entry in ytd_9m.items():
            if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in dedup_by_end.values()):
                target_q2_end = ytd_entry['_end_dt'] - timedelta(days=90)
                ytd_6m_entry = next((v for v in ytd_6m.values() if abs((v['_end_dt'] - target_q2_end).days) <= 25), None)
                if ytd_6m_entry:
                    derived_q3 = dict(ytd_entry)
                    derived_q3['_val'] = ytd_entry['_val'] - ytd_6m_entry['_val']
                    derived_q3['form'] = '10-Q-derived'
                    dedup_by_end[ytd_end] = derived_q3

        filtered_entries = sorted(dedup_by_end.values(), key=lambda x: x['_end_dt'], reverse=True)[:8]

        print(f"[{concept}] After Q2/Q3 filter: len={len(filtered_entries)}")
        if filtered_entries:
            print(f"First entry end_dt: {filtered_entries[0]['_end_dt']}, Recency cutoff: {recency_cutoff}")

        if len(filtered_entries) < 3: continue
        if filtered_entries[0]['_end_dt'] < recency_cutoff: continue
        
        # It passed!
        return [1], [2], [3], [4], [5]
        
    return [], [], [], [], []

rev_keys_edgar = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'RevenueFromContractWithCustomer']

print("Running EDRY...")
_edgar_metric("EDRY", rev_keys_edgar)

print("\nRunning ESOA...")
_edgar_metric("ESOA", rev_keys_edgar)
