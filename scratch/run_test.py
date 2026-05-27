from utils.code33_engine import get_code33_data
import time
tickers = ['AAPL', 'NVDA', 'META', 'LLY', 'AXON']
for t in tickers:
    start = time.time()
    d = get_code33_data(t, 1)
    print(f'{t}: status={d.get("status")} eps_yoy={d.get("eps_yoy")} time={time.time()-start:.1f}s')
