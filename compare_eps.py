import sys
import os
import requests
import datetime
from datetime import timedelta
import yfinance as yf

sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.sec_edgar import get_cik
from utils.finnhub_client import FINNHUB_KEY
from utils.code33_engine import get_edgar_facts, _get_fq_fy, _sf

def _fetch_edgar_eps_normalized(ticker):
    facts = get_edgar_facts(ticker)
    if not facts: return []
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    cutoff = (datetime.datetime.utcnow() - timedelta(days=365 * 5)).date()
    
    def _standalone(concepts, unit, use_first_filed=False):
        by_end = {}
        for concept in concepts:
            for e in usgaap.get(concept, {}).get('units', {}).get(unit, []):
                form = str(e.get('form', '')).upper()
                if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
                end_s = str(e.get('end', '')).strip()
                start_s = str(e.get('start', '')).strip()
                filed_s = str(e.get('filed', '')).strip()
                val = _sf(e.get('val'))
                if not end_s or not start_s or val is None: continue
                try:
                    end_dt = datetime.datetime.strptime(end_s, '%Y-%m-%d').date()
                    start_dt = datetime.datetime.strptime(start_s, '%Y-%m-%d').date()
                    filed_dt = datetime.datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else None
                except Exception: continue
                if end_dt < cutoff: continue
                if not (75 <= (end_dt - start_dt).days <= 105): continue
                entry = {
                    '_end_dt': end_dt,
                    '_filed_dt': filed_dt,
                    '_val': float(val),
                }
                if end_s not in by_end:
                    by_end[end_s] = entry
                elif filed_dt and by_end[end_s]['_filed_dt']:
                    if use_first_filed:
                        if filed_dt < by_end[end_s]['_filed_dt']: by_end[end_s] = entry
                    else:
                        if filed_dt > by_end[end_s]['_filed_dt']: by_end[end_s] = entry
        return by_end

    ni_map = _standalone(['NetIncomeLoss', 'NetIncome', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic'], 'USD', False)
    sh_map = _standalone(['WeightedAverageNumberOfDilutedSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingDiluted'], 'shares', True)
    
    try:
        splits_raw = yf.Ticker(ticker).splits
        splits = []
        for dt, ratio in splits_raw.items():
            d = dt.date() if hasattr(dt, 'date') else datetime.datetime.strptime(str(dt)[:10], '%Y-%m-%d').date()
            splits.append((d, float(ratio)))
        splits.sort(key=lambda x: x[0])
    except:
        splits = []

    results = []
    if ni_map and sh_map:
        for end_s, ni in ni_map.items():
            end_dt = ni['_end_dt']
            best_sh = None; best_diff = 31
            for sh in sh_map.values():
                d = abs((sh['_end_dt'] - end_dt).days)
                if d < best_diff:
                    best_diff = d; best_sh = sh
            if best_sh is None or best_sh['_val'] == 0: continue
            cum = 1.0
            for split_dt, ratio in splits:
                if split_dt > end_dt: cum *= ratio
            adj_shares = best_sh['_val'] * cum
            if adj_shares == 0: continue
            results.append({
                '_end_dt': end_dt,
                '_val': ni['_val'] / adj_shares,
            })
    
    results.sort(key=lambda x: x['_end_dt'], reverse=True)
    return results[:16]

def get_yfinance(ticker):
    ed = yf.Ticker(ticker).earnings_dates
    results = []
    if ed is not None and not ed.empty and 'Reported EPS' in ed.columns:
        df_ed = ed[['Reported EPS']].dropna()
        for ts, row in df_ed.iterrows():
            try:
                ann_dt = ts.date() if hasattr(ts, 'date') else datetime.datetime.strptime(str(ts)[:10], '%Y-%m-%d').date()
                val = float(row['Reported EPS'])
                results.append({'_end_dt': ann_dt, '_val': val}) # Note: ann_dt not period_end, but we'll align by date
            except Exception: pass
    return results

def get_finnhub(ticker):
    results = []
    if FINNHUB_KEY:
        try:
            r = requests.get(f'https://finnhub.io/api/v1/stock/earnings?symbol={ticker}&token={FINNHUB_KEY}', timeout=10)
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    period = item.get('period')
                    val = item.get('actual')
                    if period and val is not None:
                        dt = datetime.datetime.strptime(period, '%Y-%m-%d').date()
                        results.append({'_end_dt': dt, '_val': float(val)})
        except Exception: pass
    return results

for ticker in ['AXON', 'ANET', 'ADI']:
    print(f"\n--- {ticker} ---")
    info = yf.Ticker(ticker).info or {}
    fy_end_m = 12
    if 'lastFiscalYearEnd' in info:
        try:
            fy_end_dt = datetime.datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=datetime.timezone.utc)
            m = fy_end_dt.month
            fy_end_m = 12 if m == 1 else m
        except Exception: pass

    edgar = _fetch_edgar_eps_normalized(ticker)
    yf_data = get_yfinance(ticker)
    fh_data = get_finnhub(ticker)
    
    # Collect all unique quarters
    all_dts = []
    for d in edgar + yf_data + fh_data:
        all_dts.append(d['_end_dt'])
    
    # Group dates within 45 days
    all_dts.sort()
    grouped_dts = []
    for dt in all_dts:
        if not grouped_dts:
            grouped_dts.append([dt])
        else:
            if abs((dt - grouped_dts[-1][-1]).days) <= 60:
                grouped_dts[-1].append(dt)
            else:
                grouped_dts.append([dt])
    
    rep_dts = [sorted(g)[len(g)//2] for g in grouped_dts]
    rep_dts.sort(reverse=True)
    
    print(f"{'Quarter':<10} | {'yfinance':<10} | {'Finnhub':<10} | {'EDGAR':<10}")
    print("-" * 49)
    for dt in rep_dts[:16]:
        lbl = _get_fq_fy(dt, fy_end_m)
        yf_val = next((item['_val'] for item in yf_data if abs((item['_end_dt'] - dt).days) <= 75), None)
        fh_val = next((item['_val'] for item in fh_data if abs((item['_end_dt'] - dt).days) <= 75), None)
        ed_val = next((item['_val'] for item in edgar if abs((item['_end_dt'] - dt).days) <= 75), None)
        
        yf_str = f"{yf_val:.2f}" if yf_val is not None else "N/A"
        fh_str = f"{fh_val:.2f}" if fh_val is not None else "N/A"
        ed_str = f"{ed_val:.2f}" if ed_val is not None else "N/A"
        
        print(f"{lbl:<10} | {yf_str:<10} | {fh_str:<10} | {ed_str:<10}")
