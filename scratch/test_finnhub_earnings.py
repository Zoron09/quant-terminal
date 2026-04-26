import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("FINNHUB_KEY")
for ticker in ["ADI", "JAKK", "VTRS"]:
    r = requests.get(f"https://finnhub.io/api/v1/stock/earnings?symbol={ticker}&limit=8&token={key}")
    data = r.json()
    print(f"\n{ticker}:")
    for q in data:
        print(q)
