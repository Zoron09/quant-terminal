import sys
import importlib
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
stock_detail = importlib.import_module("pages.15_stock_detail")
get_code33_data = stock_detail.get_code33_data

data = get_code33_data("ESOA")
curr = data.get('rev', [])
prior = data.get('rev_prior', [])
lbl = data.get('rev_labels', [])

print("ESOA Rev:")
for i in range(len(curr)):
    p = prior[i]
    c = curr[i]
    pct = (c - p) / abs(p) if p else 0
    print(f"{lbl[i]}: {pct*100:.2f}% (curr={c}, prior={p})")
    
data = get_code33_data("EDRY")
curr = data.get('rev', [])
prior = data.get('rev_prior', [])
lbl = data.get('rev_labels', [])

print("\nEDRY Rev:")
for i in range(len(curr)):
    p = prior[i]
    c = curr[i]
    pct = (c - p) / abs(p) if p else 0
    print(f"{lbl[i]}: {pct*100:.2f}% (curr={c}, prior={p})")
