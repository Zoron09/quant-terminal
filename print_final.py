import sys
sys.path.append(r"C:\Users\Meet Singh\quant-terminal")
from utils.code33_engine import get_code33_data

print("1. OK verified")

for t in ['XOM', 'KO', 'AXON', 'ANET']:
    data = get_code33_data(t)
    print(f"\n{t} Revenue YoY%:")
    rev_yoy = data.get('rev_yoy', [])
    rev_labels = data.get('rev_labels', [])
    
    # Just print the last 3 or 4 valid quarters
    for i in range(len(rev_labels)):
        lbl = rev_labels[i]
        if lbl in ['Q3 2025', 'Q4 2025', 'Q1 2026']:
            val = rev_yoy[i]
            val_str = f"{val*100:+.2f}%" if val is not None else "N/A"
            print(f"  {lbl}: {val_str}")
