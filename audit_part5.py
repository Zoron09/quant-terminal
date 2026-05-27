from utils.code33_engine import get_code33_data
import traceback
results = {'green':0,'yellow':0,'red':0,'insufficient':0,'crash':0}
for t in ['NVDA','AXON','ANET','ADI','LLY','CAT','AMD','UNH','COST','MSFT','AAPL','GOOGL','META','AMZN','TSLA']:
    try:
        d = get_code33_data(t, 1)
        s = d.get('status','insufficient')
        results[s] = results.get(s,0) + 1
        print(f'{t}: {s} | eps_src={d.get("sources",{}).get("eps")}')
    except Exception as e:
        results['crash'] += 1
        print(f'CRASH {t}: {e}')
print('SUMMARY:', results)
