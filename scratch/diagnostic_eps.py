import yfinance as yf

TICKERS = ["JAKK", "ASYS", "QUIK", "INTT", "ESOA", "UTGN", "WSR", "SODI"]

for ticker in TICKERS:
    print(f"\n{'='*40}")
    print(f"{ticker}")
    t = yf.Ticker(ticker)
    try:
        df = t.earnings_dates[["Reported EPS"]].dropna()
        df = df.sort_index(ascending=False).head(8)
        print(df)
    except Exception as e:
        print(f"ERROR: {e}")
