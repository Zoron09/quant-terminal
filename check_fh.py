with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'rb') as f:
    content = f.read()
print("Contains 'finnhub':", b'finnhub' in content.lower())
print("Contains '_finnhub_fetch_eps':", b'_finnhub_fetch_eps' in content)
