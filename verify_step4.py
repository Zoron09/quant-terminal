from utils.code33_engine import get_code33_data
for t in ['NVDA','AXON','ANET','ADI','LLY','AMD','UNH','MSFT','AAPL','GOOGL']:
    try:
        d = get_code33_data(t, 1)
        print(f'{t}: {d.get("status")} | eps={d.get("eps_yoy")} | src={d.get("sources",{}).get("eps")}')
    except Exception as e:
        print(f'CRASH {t}: {e}')
