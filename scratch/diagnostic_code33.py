from utils.code33_engine import get_code33_data
for t in ['ADI','ANET','AXON','LFUS','GIII','FANG','ARCB']:
    r = get_code33_data(t)
    print(t, 'Rev Labels:', r['rev_labels'])
    print(t, 'Rev YoY:', [round(x,1) if x is not None else None for x in r['rev_yoy']])
    print()
