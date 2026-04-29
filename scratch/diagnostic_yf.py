import yfinance as yf
import pandas as pd

ticker = "CAMT"
t = yf.Ticker(ticker)

print("=== quarterly_income_stmt ===")
try:
    qi = t.quarterly_income_stmt
    if qi is not None and not qi.empty:
        eps_rows = [r for r in qi.index if 'eps' in r.lower() or 'earnings per share' in r.lower()]
        print("EPS rows found:", eps_rows)
        for row in eps_rows:
            print(f"{row}:", qi.loc[row].to_dict())
    else:
        print("Empty")
except Exception as e:
    print("Error:", e)

print("\n=== earnings_dates ===")
try:
    ed = t.earnings_dates
    print(ed[['Reported EPS']].dropna().head(12))
except Exception as e:
    print("Error:", e)
