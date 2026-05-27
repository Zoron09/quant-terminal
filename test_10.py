import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data, _c33_status

tickers = ['JPM', 'XOM', 'UNH', 'COST', 'BRK.B', 'NVZ', 'CAT', 'LLY', 'AMD', 'KO']

print("Running 10 tickers...")

for ticker in tickers:
    print(f"\n{'='*40}")
    print(f"Ticker: {ticker}")
    print(f"{'='*40}")
    try:
        data = get_code33_data(ticker)
    except Exception as e:
        print(f"Error processing {ticker}: {e}")
        continue
        
    eps_yoy = data.get('eps_yoy', [])
    rev_yoy = data.get('rev_yoy', [])
    npm = data.get('npm', [])
    
    eps_lbl = data.get('eps_labels', [])
    rev_lbl = data.get('rev_labels', [])
    npm_lbl = data.get('npm_labels', [])
    
    is_us = data.get('is_us', True)
    sector_excluded = data.get('sector_excluded', False)
    sources = data.get('sources', {})
    
    eps_src = sources.get('eps', 'insufficient')
    rev_src = sources.get('rev', 'insufficient')
    
    status, _, _ = _c33_status(eps_yoy)
    if sector_excluded:
        status = 'excluded'
        
    print(f"Code 33 status: {status.upper()}")
    print(f"Data source - EPS: {eps_src} | Revenue: {rev_src}")
    
    warnings = []
    if not is_us:
        warnings.append("Non-US company")
    if sector_excluded:
        warnings.append(f"Sector excluded: {data.get('excluded_sector_name')}")
    if data.get('is_reit'):
        warnings.append("REIT")
    if warnings:
        print(f"Warnings/Flags: {', '.join(warnings)}")
    else:
        print("Warnings/Flags: None")
        
    print("\nEPS YoY% (last 3):")
    if len(eps_yoy) >= 3:
        for lbl, y in zip(eps_lbl[-3:], eps_yoy[-3:]):
            val = f"{y:.2f}%" if y is not None else "None"
            print(f"  {lbl}: {val}")
    else:
        print("  Insufficient data")
        
    print("\nRevenue YoY% (last 3):")
    if len(rev_yoy) >= 3:
        for lbl, y in zip(rev_lbl[-3:], rev_yoy[-3:]):
            val = f"{y:.2f}%" if y is not None else "None"
            print(f"  {lbl}: {val}")
    else:
        print("  Insufficient data")
        
    print("\nNet Margin% (last 3):")
    if len(npm) >= 3:
        for lbl, y in zip(npm_lbl[-3:], npm[-3:]):
            val = f"{y:.2f}%" if y is not None else "None"
            print(f"  {lbl}: {val}")
    else:
        print("  Insufficient data")
