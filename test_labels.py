import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

print("OK")

for ticker in ['TRT', 'AXON', 'ANET']:
    print(f"\n--- {ticker} ---")
    data = get_code33_data(ticker)
    rev_yoy = data.get('rev_yoy', [])
    rev_lbl = data.get('rev_labels', [])
    for lbl, yoy in zip(rev_lbl, rev_yoy):
        print(f"  {lbl}: {yoy:.2f}%" if yoy is not None else f"  {lbl}: None")
