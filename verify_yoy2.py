import sys
import importlib
import json
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

tickers = ['ESOA', 'EDRY']

for t in tickers:
    try:
        data = get_code33_data(t)
        print(f"\n--- {t} ---")
        if not data: continue
        
        curr = data.get('rev', [])
        prior = data.get('rev_prior', [])
        lbl = data.get('rev_lbl', [])
        
        if not curr or not prior:
            print("Missing curr or prior arrays")
            continue
            
        print("Latest YoY:")
        for i in range(min(4, len(curr))):
            c = curr[i]
            p = prior[i]
            if p:
                pct = ((c - p) / abs(p)) * 100
                print(f"  {lbl[i] if i < len(lbl) else '?'}: {pct:+.2f}% (curr={c}, prior={p})")
            else:
                print(f"  {lbl[i] if i < len(lbl) else '?'}: N/A (curr={c}, prior={p})")
    except Exception as e:
        print(f"\n--- {t} --- ERROR: {e}")
