import yfinance as yf

esoa = yf.Ticker("ESOA")
inc = esoa.quarterly_income_stmt
print("ESOA YF:")
if not inc.empty:
    for k in ['Total Revenue', 'Revenue', 'Operating Revenue']:
        if k in inc.index:
            print(k)
            print(inc.loc[k])

edry = yf.Ticker("EDRY")
inc = edry.quarterly_income_stmt
print("\nEDRY YF:")
if not inc.empty:
    for k in ['Total Revenue', 'Revenue', 'Operating Revenue']:
        if k in inc.index:
            print(k)
            print(inc.loc[k])
