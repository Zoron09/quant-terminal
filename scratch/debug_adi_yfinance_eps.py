import yfinance as yf

t = yf.Ticker("ADI")
df = t.earnings_dates[["Reported EPS"]].dropna()
df = df.sort_index(ascending=False).head(12)
print("ADI yfinance earnings_dates Reported EPS (12 quarters):")
print(df)
