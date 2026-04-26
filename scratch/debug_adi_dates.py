import yfinance as yf

t = yf.Ticker("ADI")
df = t.earnings_dates[["Reported EPS"]].dropna()
df = df.sort_index(ascending=False).head(12)
print("ADI earnings dates and EPS:")
for date, row in df.iterrows():
    print(f"{date.date()} : {row['Reported EPS']}")
