import requests
r = requests.get("https://finnhub.io/api/v1/stock/earnings", params={"symbol": "CAMT", "token": "d78gb81r01qsbhvtqmsgd78gb81r01qsbhvtqmt0"})
print("Finnhub status:", r.status_code)
import json
print("Finnhub data:", json.dumps(r.json(), indent=2))
