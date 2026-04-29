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

tickers = {
    'TSLA': [(-11.8, 11.6, -3.1)],
    'PLTR': [(48.0, 62.8, 70.0)],
    'SOFI': [(33.0, 44.0, 32.5)],
    'NVDA': [(69, 56, 62)],
    'META': [(21.6, 26.2, 23.8)],
    'APP':  [(40.3, 77.0, 68.2)],
    'CRWD': [(19.8, 21.3, 22.2)],
    'MSFT': [(13.0, 18.0, 17.0)],
    'ORCL': [(12.2, 14.2, 21.7)],
    'HIMS': [(110.7, 72.6, 49.2)],
}

for ticker, (expected,) in tickers.items():
    d = p.get_code33_data(ticker)
    rev = d.get('rev', [])
    rev_ends = d.get('rev_end_dates', [])
    rates = p._compute_yoy(rev, rev_ends) if rev and rev_ends else []
    valid = [r for r in rates if r is not None]
    last3 = valid[-3:] if len(valid) >= 3 else valid
    print(f"{ticker}: {[round(r,1) for r in last3]} | expected {list(expected)} | src: {d.get('sources',{}).get('rev','?')}")
