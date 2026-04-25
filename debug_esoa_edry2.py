import sys
import importlib
import json

sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
_fmp_fetch_revenue_ni = stock_detail._fmp_fetch_revenue_ni

esoa_fmp = _fmp_fetch_revenue_ni("ESOA")
edry_fmp = _fmp_fetch_revenue_ni("EDRY")

with open(r"C:\Users\Meet Singh\quant-terminal\debug_esoa_edry_fmp.json", "w") as f:
    json.dump({"ESOA": esoa_fmp, "EDRY": edry_fmp}, f, indent=2, default=str)
