import sys
sys.path.insert(0, '.')
import streamlit as st
st.cache_data = lambda **kw: (lambda f: f)

import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "fifteen_stock_detail",
    pathlib.Path("pages/15_stock_detail.py")
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

print("--- TESTING SOFI ---")
p.get_code33_data('SOFI')

print("--- TESTING NVDA ---")
p.get_code33_data('NVDA')
