import sys
import streamlit as st
import requests
from datetime import datetime, timedelta
sys.path.insert(0, r'C:\Users\Meet Singh\quant-terminal')
from pages.15_stock_detail import _sf, _date_first_yoy, _build_margin_pool, _fmp_fetch_revenue_ni, get_edgar_facts, rev_keys_edgar, ni_keys_edgar, eps_keys_edgar
FINNHUB_KEY = ''
def _finnhub_quarterly_series(x): return [],[],[]
