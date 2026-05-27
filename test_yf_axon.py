import yfinance as yf
tk = yf.Ticker('AXON')
inc = tk.quarterly_income_stmt
print(inc.loc[[r for r in inc.index if 'EPS' in r or 'Earnings Per Share' in r]] if any('EPS' in r or 'Earnings Per Share' in r for r in inc.index) else 'No EPS row found')
print('columns:', list(inc.columns))
