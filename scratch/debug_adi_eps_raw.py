import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("FINNHUB_API_KEY")
r = requests.get(f"https://finnhub.io/api/v1/stock/earnings?symbol=ADI&limit=12&token={key}")
data = r.json()

print("RAW FINNHUB /stock/earnings for ADI:")
for q in data:
    print(q)
