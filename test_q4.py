import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

tickers = ['LLY', 'KO', 'CAT', 'AMD', 'AXON', 'ANET', 'ADI']

for ticker in tickers:
    print(f"\n--- {ticker} ---")
    data = get_code33_data(ticker)
    eps_yoy = data.get('eps_yoy', [])
    eps_lbl = data.get('eps_labels', [])
    eps_src = data.get('eps_sources', [])
    
    # We want to print the last 6 quarters to see Q4 explicitly
    for lbl, yoy, src in zip(eps_lbl[-6:], eps_yoy[-6:], eps_src[-6:]):
        val = f"{yoy:.2f}%" if yoy is not None else "None"
        print(f"  {lbl}: {val} (source: {src})")
