import sys
import os
import csv
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add terminal root to path so we can import from utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Silence Streamlit caching warnings before importing code33_engine
import functools
import types
import sys

# Mock streamlit
if 'streamlit' not in sys.modules:
    class MockSt:
        def cache_data(self, *args, **kwargs):
            if len(args) == 1 and callable(args[0]):
                return args[0]
            def decorator(func):
                @functools.wraps(func)
                def wrapper(*f_args, **f_kwargs):
                    return func(*f_args, **f_kwargs)
                return wrapper
            return decorator
    sys.modules['streamlit'] = MockSt()

from utils.code33_engine import get_code33_data, _c33_status

logging.basicConfig(level=logging.INFO, format='%(message)s')

def _last3_valid(rates):
    valid = [r for r in rates if r is not None]
    if len(valid) < 3: 
        return [None]*3
    return valid[-3:]

def get_overall_status(c33_data):
    eps_raw = c33_data.get('eps_yoy', [])
    rev_raw = c33_data.get('rev_yoy', [])
    npm_raw = c33_data.get('npm', [])
    
    eps3 = _last3_valid(eps_raw)
    rev3 = _last3_valid(rev_raw)
    npm3 = _last3_valid(npm_raw)
    
    eps_status, _, _ = _c33_status(eps3)
    rev_status, _, _ = _c33_status(rev3)
    npm_status, _, _ = _c33_status(npm3)
    
    eps_prior = c33_data.get('eps_prior_vals', [])
    is_preprofit = any(v is not None and v < 0 for v in eps_prior[-3:]) if eps_prior else False
    is_us = c33_data.get('is_us', True)
    sector_excluded = c33_data.get('sector_excluded', False)
    
    if is_preprofit or not is_us or sector_excluded:
        overall = 'NOT APPLICABLE'
    else:
        statuses = [eps_status, rev_status, npm_status]
        if all(s == 'insufficient' for s in statuses):
            overall = 'INSUFFICIENT'
        elif 'red' in statuses:
            overall = 'BROKEN'
        elif 'yellow' in statuses:
            overall = 'AT RISK'
        elif all(s == 'green' for s in statuses):
            overall = 'ACTIVE'
        elif 'insufficient' in statuses:
            overall = 'INSUFFICIENT'
        else:
            overall = 'ACTIVE'
            
    return overall, eps3, rev3, npm3

def format_rate(val):
    if val is None:
        return 'N/A'
    return f"{val:.1f}%"

def process_ticker(ticker):
    try:
        data = get_code33_data(ticker)
        status, eps3, rev3, npm3 = get_overall_status(data)
        
        row_all = {'Symbol': ticker, 'Status': status}
        row_active = None
        
        if status == 'ACTIVE':
            row_active = {
                'Symbol': ticker,
                'EPS_Q-2': format_rate(eps3[0]), 'EPS_Q-1': format_rate(eps3[1]), 'EPS_Q0': format_rate(eps3[2]),
                'Rev_Q-2': format_rate(rev3[0]), 'Rev_Q-1': format_rate(rev3[1]), 'Rev_Q0': format_rate(rev3[2]),
                'NPM_Q-2': format_rate(npm3[0]), 'NPM_Q-1': format_rate(npm3[1]), 'NPM_Q0': format_rate(npm3[2])
            }
        return ticker, status, row_all, row_active, None
    except Exception as e:
        return ticker, 'ERROR', {'Symbol': ticker, 'Status': 'ERROR'}, None, str(e)

def main():
    if len(sys.argv) < 2:
        print("Usage: python fast_batch_c33_scan.py <path_to_csv>")
        sys.exit(1)
        
    csv_file = sys.argv[1]
    
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found.")
        sys.exit(1)
        
    # Read tickers
    tickers = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'Symbol' in row:
                tickers.append(row['Symbol'].strip())
                
    if not tickers:
        print("No tickers found in CSV. Make sure there is a 'Symbol' column.")
        sys.exit(1)
        
    print(f"Found {len(tickers)} tickers. Starting FAST batch scan with 10 workers...")
    
    # Create batch_results directory
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'batch_results')
    os.makedirs(out_dir, exist_ok=True)
    
    all_file = os.path.join(out_dir, 'code33_all.csv')
    active_file = os.path.join(out_dir, 'code33_active.csv')
    
    active_count = 0
    completed_count = 0
    
    with open(all_file, 'w', newline='', encoding='utf-8') as f_all, \
         open(active_file, 'w', newline='', encoding='utf-8') as f_active:
        
        all_writer = csv.DictWriter(f_all, fieldnames=['Symbol', 'Status'])
        all_writer.writeheader()
        
        active_fieldnames = ['Symbol', 'EPS_Q-2', 'EPS_Q-1', 'EPS_Q0', 'Rev_Q-2', 'Rev_Q-1', 'Rev_Q0', 'NPM_Q-2', 'NPM_Q-1', 'NPM_Q0']
        active_writer = csv.DictWriter(f_active, fieldnames=active_fieldnames)
        active_writer.writeheader()
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all tasks
            future_to_ticker = {executor.submit(process_ticker, t): t for t in tickers}
            
            for future in as_completed(future_to_ticker):
                ticker, status, row_all, row_active, err = future.result()
                completed_count += 1
                
                all_writer.writerow(row_all)
                
                if status == 'ACTIVE' and row_active:
                    active_count += 1
                    active_writer.writerow(row_active)
                    f_active.flush()
                
                f_all.flush()
                
                if err:
                    print(f"[{completed_count}/{len(tickers)}] Error processing {ticker}: {err}")
                else:
                    if completed_count % 5 == 0 or completed_count == 1:
                        print(f"[{completed_count}/{len(tickers)}] Processed {ticker} -> {status}")
                
                # Add tiny sleep to prevent hammering
                time.sleep(0.05)
            
    print(f"\nScan complete! Results saved in batch_results/")
    print(f"Total Processed: {len(tickers)} | Active Candidates: {active_count}")
    
if __name__ == "__main__":
    main()
