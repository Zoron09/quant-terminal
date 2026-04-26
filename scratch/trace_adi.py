import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.code33_engine import get_code33_data, _yfinance_fetch_eps, _finnhub_fetch_eps, _date_first_yoy

ticker = "ADI"

print("1. Fetching from yfinance:")
yf_vals, yf_lbls, yf_ends = _yfinance_fetch_eps(ticker)
for v, l, e in zip(yf_vals, yf_lbls, yf_ends):
    print(f"  {e} ({l}): {v}")

print("\n2. Fetching from Finnhub:")
fh_vals, fh_lbls, fh_ends = _finnhub_fetch_eps(ticker)
for v, l, e in zip(fh_vals, fh_lbls, fh_ends):
    print(f"  {e} ({l}): {v}")

print("\n3. Testing _date_first_yoy with yfinance data as primary:")
# In get_code33_data, _date_first_yoy is called with yfinance data as the primary
results = _date_first_yoy(yf_vals, yf_ends, [], [], None, None, None, None, fy_end_m=10)
eps_yoy, eps_labels, eps_ends, eps_prior_vals = results
for i in range(len(eps_yoy)):
    print(f"  Curr: {eps_ends[i]} ({eps_labels[i]}), Rate: {eps_yoy[i]:.2f}%, Prior Val: {eps_prior_vals[i]}")

print("\n4. Full get_code33_data output for EPS YoY:")
data = get_code33_data(ticker)
for i in range(len(data['eps_yoy'])):
    print(f"  Label: {data['eps_labels'][i]}, Rate: {data['eps_yoy'][i]:.2f}%")
