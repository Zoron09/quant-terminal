import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data, _fetch_edgar_eps_normalized, ticker
import utils.code33_engine
utils.code33_engine.ticker = 'AXON'

data = get_code33_data('AXON')
print("Raw EPS from get_code33_data:")
print(data.get('eps'))
print("Raw End Dates:")
print(data.get('eps_end_dates'))

edgar_eps, edgar_eps_lbl, edgar_eps_end, edgar_eps_fy, edgar_eps_fp, edgar_eps_form = _fetch_edgar_eps_normalized()
print("\nDirect from _fetch_edgar_eps_normalized:")
for val, dt, frm in zip(edgar_eps, edgar_eps_end, edgar_eps_form):
    print(f"Date: {dt}, EPS: {val}, Form: {frm}")
