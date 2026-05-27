from utils.code33_engine import get_code33_data
for t in ['LLY', 'AXON', 'AMD', 'META', 'NVDA']:
    d = get_code33_data(t, 1)
    print(f'{t}: engine_status={d.get("status")}')
