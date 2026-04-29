import requests
import yfinance as yf

# 1. EDGAR Fetch
headers = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}
url = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000889331.json'

print("--- EDGAR: us-gaap/EarningsPerShareDiluted ---")
try:
    r = requests.get(url, headers=headers, timeout=10)
    data = r.json()
    eps = data.get('facts', {}).get('us-gaap', {}).get('EarningsPerShareDiluted', {}).get('units', {}).get('USD/shares', [])
    
    count = 0
    for e in eps:
        end = e.get('end', '')
        form = e.get('form', '')
        if end >= '2024-09-01' and end <= '2025-01-31' and form in ('10-Q', '10-K'):
            print(f"accn: {e.get('accn')} | start: {e.get('start')} | end: {e.get('end')} | val: {e.get('val')} | form: {e.get('form')} | filed: {e.get('filed')}")
            count += 1
            
    if count == 0:
        print("No entries found matching criteria.")
except Exception as e:
    print(f"Error fetching EDGAR: {e}")

print("\n--- YFINANCE: Earnings Dates ---")
try:
    t = yf.Ticker('LFUS')
    ed = t.earnings_dates
    if ed is not None and not ed.empty:
        df = ed.reset_index()
        for idx, row in df.iterrows():
            d = row['Earnings Date']
            d_str = d.strftime('%Y-%m-%d')
            # Look at earnings dates reported around the target window (or slightly after)
            if '2024-09-01' <= d_str <= '2025-03-31':
                eps_rep = row.get('Reported EPS', 'N/A')
                print(f"Earnings Date: {d_str} | Reported EPS: {eps_rep}")
    else:
        print("No earnings dates found in yfinance.")
except Exception as e:
    print(f"Error fetching yfinance: {e}")
