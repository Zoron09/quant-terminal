from utils.code33_engine import get_code33_data
tickers = ['NVDA', 'AXON', 'ANET', 'COST', 'UNH', 'AMD', 'LLY', 'MSFT', 'AAPL', 'GOOGL']
for t in tickers:
    try:
        d = get_code33_data(t, 1)
        print(f'OK {t}: status={d.get("status")}')
    except Exception as e:
        print(f'CRASH {t}: {e}')
