with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()
idx = content.lower().find('_finnhub_fetch_eps')
start = content.rfind('\n', 0, max(0, idx - 200)) + 1
end = content.find('\n\n', idx + 300)
print(content[start:end])
