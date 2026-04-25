import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

for t in ['ESOA', 'EDRY']:
    data = get_code33_data(t)
    print(f"\n--- {t} KEYS ---")
    for k, v in data.items():
        print(f"  {k}: {v}")
