import sys
import os
from datetime import datetime

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.code33_engine import get_code33_data, get_edgar_facts
import yfinance as yf

TICKERS = ['ADI', 'AXON', 'ANET', 'JAKK', 'ASYS', 'QUIK', 'INTT', 'ESOA', 'UTGN', 'SODI']
EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

def fetch_edgar_eps(ticker):
    rows = []
    try:
        facts = get_edgar_facts(ticker)
        if not facts: return rows
        us_gaap = facts.get('facts', {}).get('us-gaap', {})
        eps_keys = ['EarningsPerShareDiluted', 'EarningsPerShareBasic']
        for k in eps_keys:
            if k in us_gaap:
                units = us_gaap[k].get('units', {})
                arr = None
                if 'USD/shares' in units: arr = units['USD/shares']
                elif 'USD' in units: arr = units['USD']
                elif len(units) > 0: arr = list(units.values())[0]
                
                if arr:
                    for item in arr:
                        if item.get('form', '') not in ['10-Q', '10-K', '8-K']: continue
                        if item.get('start') and item.get('end'):
                            try:
                                sd = datetime.strptime(item['start'], '%Y-%m-%d').date()
                                ed = datetime.strptime(item['end'], '%Y-%m-%d').date()
                                days = (ed - sd).days
                                if 80 <= days <= 105:
                                    rows.append({'end': ed.isoformat(), 'val': float(item['val'])})
                            except: pass
                    if len(rows) > 0: break
    except: pass
    
    # Deduplicate keeping the latest filing value for each end date (effectively simulating the engine's behavior)
    dedup = {}
    for r in rows: dedup[r['end']] = r['val']
    res = [{'end': k, 'val': v} for k, v in dedup.items()]
    res.sort(key=lambda x: x['end'], reverse=True)
    return res

def fetch_yfinance_eps(ticker):
    rows = []
    try:
        ed = yf.Ticker(ticker).earnings_dates
        if ed is not None and not ed.empty and 'Reported EPS' in ed.columns:
            df = ed[['Reported EPS']].dropna().sort_index(ascending=False).head(12)
            for ts, row in df.iterrows():
                try:
                    dt = ts.date() if hasattr(ts, 'date') else datetime.strptime(str(ts)[:10], '%Y-%m-%d').date()
                    v = float(row['Reported EPS'])
                    import math
                    if not math.isnan(v):
                        rows.append({'end': dt.isoformat(), 'val': v})
                except: pass
    except: pass
    return rows

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

def _get_fy_end_month(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        if 'lastFiscalYearEnd' in info:
            import datetime as dt2
            fy_end_dt = dt2.datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=dt2.timezone.utc)
            return fy_end_dt.month
    except: pass
    return 12

def run_audit():
    output_lines = []
    header = f"{'ticker':<6} | {'quarter':<13} | {'period_end':<10} | {'yf_eps':<8} | {'edgar_eps':<9} | {'terminal_yoy%'}"
    output_lines.append(header)
    output_lines.append("-" * len(header))
    
    for ticker in TICKERS:
        try:
            t_data = get_code33_data(ticker)
            term_dict = {lbl: yoy for lbl, yoy in zip(t_data.get('eps_labels', []), t_data.get('eps_yoy', []))}
        except Exception as e:
            output_lines.append(f"{ticker:<6} | ERROR FETCHING TERMINAL DATA: {e}")
            continue
            
        fy_end_m = _get_fy_end_month(ticker)
        y_rows = fetch_yfinance_eps(ticker)
        e_rows = fetch_edgar_eps(ticker)
        
        for er in e_rows[:12]:
            e_dt = datetime.strptime(er['end'], '%Y-%m-%d').date()
            e_val = er['val']
            
            best_yf = None
            best_diff = 999
            for yr in y_rows:
                y_dt = datetime.strptime(yr['end'], '%Y-%m-%d').date()
                diff = (y_dt - e_dt).days
                if 0 <= diff <= 90 and diff < best_diff:
                    best_yf = yr['val']
                    best_diff = diff
                    
            gap = 0.0
            if best_yf is not None and e_val != 0:
                gap = abs(best_yf - e_val) / abs(e_val) * 100
            elif best_yf is not None and e_val == 0:
                gap = 100.0 if best_yf != 0 else 0.0
                
            if best_yf is None: y_str = "N/A"
            else: y_str = f"{best_yf:.3f}"
            e_str = f"{e_val:.3f}"
            
            if gap > 5.0 or (best_yf is not None and best_yf != e_val and e_val == 0):
                lbl = _get_fq_fy(e_dt, fy_end_m)
                term = term_dict.get(lbl, "N/A")
                t_str = f"{term:+.1f}%" if isinstance(term, float) else term
                output_lines.append(f"{ticker:<6} | {lbl:<13} | {e_dt.isoformat():<10} | {y_str:<8} | {e_str:<9} | {t_str}")

    out_text = "\n".join(output_lines)
    print(out_text)
    with open("tools/eps_source_audit.txt", "w", encoding="utf-8") as f:
        f.write(out_text)

if __name__ == '__main__':
    run_audit()
