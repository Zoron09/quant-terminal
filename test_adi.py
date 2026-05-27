import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

ticker = 'ADI'
print(f"--- {ticker} ---")
data = get_code33_data(ticker)

rev_yoy = data.get('rev_yoy', [])
rev_lbl = data.get('rev_labels', [])
npm_vals = data.get('npm', [])
npm_lbl = data.get('npm_labels', [])

print("\nFinal Revenue YoY%:")
for lbl, yoy in zip(rev_lbl, rev_yoy):
    print(f"  {lbl}: {yoy:.2f}%" if yoy is not None else f"  {lbl}: None")
    
print("\nFinal Net Profit Margin% (Raw):")
for lbl, margin in zip(npm_lbl, npm_vals):
    print(f"  {lbl}: {margin:.2f}%" if margin is not None else f"  {lbl}: None")
