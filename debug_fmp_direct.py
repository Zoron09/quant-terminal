import os
import sys
import json
import requests
from dotenv import load_dotenv

sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
load_dotenv(r"C:\Users\Meet Singh\quant-terminal\.env")
FMP_API_KEY = os.getenv('FMP_API_KEY', '')

def fetch_fmp_stable(symbol):
    r = requests.get(
        "https://financialmodelingprep.com/stable/income-statement",
        params={'symbol': symbol, 'period': 'quarter', 'limit': 12, 'apikey': FMP_API_KEY},
        timeout=10
    )
    return {"status": r.status_code, "text": r.text[:500]}

print("ESOA:", fetch_fmp_stable("ESOA"))
print("EDRY:", fetch_fmp_stable("EDRY"))
