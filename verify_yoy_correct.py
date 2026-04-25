import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

tickers = ['ESOA', 'EDRY', 'JAKK', 'ASYS', 'QUIK', 'SODI', 'UTGN', 'WSR']

for t in tickers:
    try:
        data = get_code33_data(t)
        print(f"\n--- {t} ---")
        if not data: continue
        
        rev_yoy = data.get('rev_yoy', [])
        rev_labels = data.get('rev_labels', [])
        
        print("Latest YoY:")
        for i in range(min(5, len(rev_yoy))):
            lbl = rev_labels[i] if i < len(rev_labels) else '?'
            pct = rev_yoy[i] * 100
            print(f"  {lbl}: {pct:+.2f}%")
            
        print("Source:")
        print(f"  {data.get('sources', {}).get('rev', 'unknown')}")
    except Exception as e:
        print(f"\n--- {t} --- ERROR: {e}")
