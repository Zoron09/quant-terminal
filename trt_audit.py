import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data
import yfinance as yf
from datetime import datetime, timezone

ticker = 'TRT'
info = yf.Ticker(ticker).info or {}

fy_end_month = 12
if 'lastFiscalYearEnd' in info:
    try:
        fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
        m = fy_end_dt.month
        fy_end_month = 12 if m == 1 else m
    except Exception:
        pass

print(f"\n--- {ticker} ---")
print(f"lastFiscalYearEnd: {info.get('lastFiscalYearEnd')}")
if 'lastFiscalYearEnd' in info:
    print(f"Timestamp date: {datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)}")
print(f"Detected fy_end_m: {fy_end_month}")

print("\nRunning get_code33_data to see raw outputs...")
data = get_code33_data(ticker)

rev_ends = data.get('_rev_ends_raw', data.get('rev_labels', [])) # I'll just print the labels and see if I can find the ends
# Actually, I'll extract it manually for TRT
import json
print("\nFinal Revenue Dates and Labels:")
# get_code33_data doesn't return the raw dates for rev YoY, but I can print them from data
# wait, code33 engine only returns labels. I will modify the script to call the functions directly.

from utils.code33_engine import _get_fq_fy
test_dates = [
    datetime(2023, 3, 31).date(),
    datetime(2023, 6, 30).date(),
    datetime(2023, 9, 30).date(),
    datetime(2023, 12, 31).date(),
    datetime(2024, 3, 31).date(),
    datetime(2024, 6, 30).date(),
    datetime(2024, 9, 30).date(),
]
print("\nGenerated Labels for raw period-end dates (assuming these standard ends):")
for d in test_dates:
    print(f"{d} -> {_get_fq_fy(d, fy_end_month)}")
