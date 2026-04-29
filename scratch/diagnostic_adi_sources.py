import sys, os, requests
sys.path.insert(0, '.')
os.environ.setdefault('STREAMLIT_SERVER_HEADLESS', 'true')
import streamlit as st; st.cache_data = lambda *a,**kw:(lambda f:f)
from utils.code33_engine import get_code33_data
r = get_code33_data('ADI')
print('Sources:', r.get('sources'))
print('Rev labels:', r['rev_labels'])
print('Rev YoY:', [round(x,1) if x is not None else None for x in r['rev_yoy']])

url = 'https://financialmodelingprep.com/stable/income-statement'
params = {'symbol': 'ADI', 'period': 'quarter', 'limit': 8, 'apikey': '331cjm2MhPdmr04uevXTD3BKEJnOBlIB'}
r = requests.get(url, params=params)
print('FMP status:', r.status_code)
if r.status_code == 200:
    for q in r.json()[:8]:
        print(f"date={q['date']} revenue={q['revenue']:,}")
