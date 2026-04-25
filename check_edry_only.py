import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

data = get_code33_data("EDRY")
rev_yoy = data.get('rev_yoy', [])
rev_labels = data.get('rev_labels', [])
rev_ends = data.get('rev_end_dates', [])
print(f"EDRY rev_yoy: {rev_yoy}")
print(f"EDRY rev_labels: {rev_labels}")
print(f"EDRY rev_end_dates: {rev_ends}")
print(f"EDRY sources: {data.get('sources')}")
