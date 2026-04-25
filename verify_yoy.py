import sys
import importlib
import json
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

tickers = ['ESOA', 'EDRY', 'JAKK', 'ASYS', 'QUIK', 'SODI', 'UTGN', 'WSR']

for t in tickers:
    try:
        data = get_code33_data(t)
        print(f"\n--- {t} ---")
        if not data:
            print("No data returned")
            continue
        
        rev_yoy = data.get('rev', [])
        rev_labels = data.get('rev_lbl', [])
        print("Rev YoY: ", rev_yoy[:5])
        print("Rev Lbl: ", rev_labels[:5])
    except Exception as e:
        print(f"\n--- {t} --- ERROR: {e}")

