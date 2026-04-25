import sys
import os
import json
import importlib

sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")

stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

print("ESOA Code 33 Data:")
esoa_data = get_code33_data("ESOA")
print(json.dumps(esoa_data, indent=2, default=str))

print("\n==================\n")
print("EDRY Code 33 Data:")
edry_data = get_code33_data("EDRY")
print(json.dumps(edry_data, indent=2, default=str))

