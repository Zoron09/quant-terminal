"""
Temporary debug script — run once, then delete.
Calls get_code33_data('ORCL') via a minimal reimplementation
of the FMP + EDGAR merge so we can see the REV pool.
"""
import os, sys, requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

FMP_API_KEY = os.getenv('FMP_API_KEY', '')
EDGAR_UA    = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

from utils.sec_edgar import get_cik

TICKER = 'ORCL'

def _sf(v, default=None):
    if v is None: return default
    import numpy as np
    try:
        if isinstance(v, float) and np.isnan(v): return default
    except Exception: pass
    try: return float(v)
    except Exception: return default


# ── FMP revenue fetch ────────────────────────────────────────────────────────
print("=== FMP fetch ===")
try:
    r = requests.get(
        "https://financialmodelingprep.com/stable/income-statement",
        params={'symbol': TICKER, 'period': 'quarter', 'limit': 5, 'apikey': FMP_API_KEY},
        timeout=10
    )
    r.raise_for_status()
    data = r.json() if isinstance(r.json(), list) else []
    rows = []
    for item in data:
        date_str = str(item.get('date','')).strip()
        revenue   = _sf(item.get('revenue'))
        if not date_str or revenue is None: continue
        try: dt = datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception: continue
        rows.append((dt, float(revenue)))
    rows = sorted(rows, key=lambda x: x[0], reverse=True)[:8]
    rows.reverse()
    fmp_rev_ends = [r[0].isoformat() for r in rows]
    fmp_rev_vals = [r[1] for r in rows]
    print(f"FMP rows ({len(fmp_rev_ends)}): {list(zip(fmp_rev_ends, fmp_rev_vals))}")
except Exception as e:
    print(f"FMP error: {e}")
    fmp_rev_ends, fmp_rev_vals = [], []


# ── EDGAR revenue fetch ──────────────────────────────────────────────────────
print("\n=== EDGAR fetch ===")
REV_CONCEPTS = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet',
    'RevenueFromContractWithCustomer',
]
edgar_rev_ends, edgar_rev_vals = [], []
try:
    cik = get_cik(TICKER)
    print(f"CIK: {cik}")
    r = requests.get(
        f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
        headers=EDGAR_UA, timeout=15
    )
    r.raise_for_status()
    facts   = r.json()
    usgaap  = facts.get('facts', {}).get('us-gaap', {})
    cutoff  = (datetime.utcnow() - timedelta(days=365*5)).date()
    recency = (datetime.utcnow() - timedelta(days=548)).date()

    for concept in REV_CONCEPTS:
        entries = usgaap.get(concept, {}).get('units', {}).get('USD', [])
        if not entries:
            print(f"  concept {concept}: no entries")
            continue
        print(f"  concept {concept}: {len(entries)} raw entries")

        dedup = {}
        for e in entries:
            form = str(e.get('form','')).strip().upper()
            if form not in ('10-Q','10-K'): continue
            end_str   = str(e.get('end','')).strip()
            start_str = str(e.get('start','')).strip()
            val       = _sf(e.get('val'))
            if not end_str or not start_str or val is None: continue
            try:
                end_dt   = datetime.strptime(end_str,   '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
            except Exception: continue
            if end_dt < cutoff: continue
            dur = (end_dt - start_dt).days
            if dur < 80 or dur > 105: continue
            filed_str = str(e.get('filed','')).strip()
            try:    filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date() if filed_str else None
            except: filed_dt = None
            cur = dedup.get(end_dt)
            if cur is None or (filed_dt and (cur.get('_filed_dt') is None or filed_dt > cur['_filed_dt'])):
                c = dict(e); c['_end_dt']=end_dt; c['_filed_dt']=filed_dt; c['_val']=float(val)
                dedup[end_dt] = c

        # strip old 10-K if 10-Q covers same quarter
        latest_q = max((v['_end_dt'] for v in dedup.values() if str(v.get('form','')).strip().upper()=='10-Q'), default=None)
        if latest_q:
            dedup = {k:v for k,v in dedup.items()
                     if str(v.get('form','')).strip().upper()=='10-Q' or v['_end_dt']>latest_q}

        filtered = sorted(dedup.values(), key=lambda x: x['_end_dt'], reverse=True)[:8]
        if len(filtered) < 3:
            print(f"    → only {len(filtered)} quarters after filter — skip")
            continue
        if filtered[0]['_end_dt'] < recency:
            print(f"    → most recent {filtered[0]['_end_dt']} older than recency cutoff — skip")
            continue

        filtered.reverse()
        edgar_rev_ends = [x['_end_dt'].isoformat() for x in filtered]
        edgar_rev_vals = [x['_val'] for x in filtered]
        print(f"    → USING {concept}: {len(edgar_rev_ends)} quarters")
        print(f"    → EDGAR rows: {list(zip(edgar_rev_ends, edgar_rev_vals))}")
        break
except Exception as e:
    print(f"EDGAR error: {e}")


# ── Pool merge (same logic as _normalize_to_pool) ────────────────────────────
print("\n=== Pool merge ===")
entries_list = [
    (fmp_rev_vals, fmp_rev_ends, 'FMP'),
    (edgar_rev_vals, edgar_rev_ends, 'EDGAR'),
]
pool = []
for vals, ends, src in entries_list:
    for v, e in zip(vals, ends):
        if v is None or e is None: continue
        try: dt = datetime.strptime(e, '%Y-%m-%d').date()
        except: continue
        pool.append({'dt': dt, 'val': float(v), 'src': src})

pool.sort(key=lambda x: x['dt'], reverse=True)
deduped = []
for entry in pool:
    dup = False
    for kept in deduped:
        if abs((entry['dt'] - kept['dt']).days) <= 45:
            dup = True; break
    if not dup:
        deduped.append(entry)

deduped = deduped[:8]
deduped.reverse()

rev_ends = [e['dt'].isoformat() for e in deduped]
rev_vals = [e['val'] for e in deduped]
sources  = [e['src'] for e in deduped]

print(f"\nFINAL REV pool ({len(rev_ends)} quarters):")
for e, v, s in zip(rev_ends, rev_vals, sources):
    print(f"  {e}  {v:>15,.0f}  [{s}]")

# ── YoY preview ──────────────────────────────────────────────────────────────
print("\n=== YoY rates ===")
date_val_map = {}
for e, v in zip(rev_ends, rev_vals):
    try: date_val_map[datetime.strptime(e,'%Y-%m-%d').date()] = float(v)
    except: pass

for e, v in zip(rev_ends, rev_vals):
    try:
        cur_dt = datetime.strptime(e,'%Y-%m-%d').date()
        try:    tgt = cur_dt.replace(year=cur_dt.year-1)
        except: tgt = cur_dt - timedelta(days=365)
        prior = None; best = 46
        for dt2, v2 in date_val_map.items():
            d = abs((dt2-tgt).days)
            if d < best: best=d; prior=v2
        if prior and prior != 0:
            yoy = (float(v) - prior) / abs(prior) * 100
            print(f"  {e}  YoY={yoy:+.1f}%  (prior={prior:,.0f})")
        else:
            print(f"  {e}  YoY=N/A  (no prior found within 45d of {tgt})")
    except Exception as ex:
        print(f"  {e}  error: {ex}")
