import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

tickers = ['XOM', 'KO', 'AXON', 'ANET']
for t in tickers:
    data = get_code33_data(t)
    if 'error' in data:
        print(f"{t}: Error - {data['error']}")
        continue
    
    print(f"\n{t} Raw Data Keys: {list(data.keys())}")
    print(f"rev_yoy: {data.get('rev_yoy')}")
    print(f"eps_yoy: {data.get('eps_yoy')}")
    print(f"sources: {data.get('sources')}")
    print(f"rev_labels: {data.get('rev_labels')}")
