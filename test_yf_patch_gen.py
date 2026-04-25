import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")

# Apply patch to test
original_get_code33_data = stock_detail.get_code33_data

def patched_get_code33_data(ticker):
    # we just mock the yf injection right in the middle
    import yfinance as _yf
    # let's just write a test copy of get_code33_data logic that injects yf
    pass

import inspect
source = inspect.getsource(original_get_code33_data)
# Let's write the patched version to a file and run it
patched = source.replace("    # ── Revenue YoY ───────────────────────────────────────────────────────────",
"""
    if not fmp_rev and yf_rev:
        fmp_rev, fmp_rev_end = yf_rev, yf_rev_end
        fmp_rev_fy, fmp_rev_fp = [None]*len(yf_rev), [None]*len(yf_rev)
    if not fmp_ni and yf_ni:
        fmp_ni, fmp_ni_end = yf_ni, yf_ni_end
        fmp_ni_fy, fmp_ni_fp = [None]*len(yf_ni), [None]*len(yf_ni)

    # ── Revenue YoY ───────────────────────────────────────────────────────────""")

with open(r"C:\Users\Meet Singh\quant-terminal\test_yf_patch.py", "w") as f:
    f.write("import sys\n")
    f.write("import streamlit as st\n")
    f.write("import requests\n")
    f.write("from datetime import datetime, timedelta\n")
    f.write("sys.path.insert(0, r'C:\\Users\\Meet Singh\\quant-terminal')\n")
    f.write("from pages.15_stock_detail import _sf, _date_first_yoy, _build_margin_pool, _fmp_fetch_revenue_ni, get_edgar_facts, rev_keys_edgar, ni_keys_edgar, eps_keys_edgar\n")
    f.write("FINNHUB_KEY = ''\n")
    f.write("def _finnhub_quarterly_series(x): return [],[],[]\n")
    f.write(patched.replace("@st.cache_data(ttl=3600, show_spinner=False)", "").replace("_finnhub_fetch_eps(ticker)", "_finnhub_quarterly_series([])"))
    f.write("\n\nprint('ESOA:', get_code33_data('ESOA'))\n")
    f.write("print('EDRY:', get_code33_data('EDRY'))\n")
