with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()
idx = content.find('def _finnhub_fetch_eps')
end = content.find('\n\n\n', idx + 100)
print(content[idx:end])
