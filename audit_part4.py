from utils.code33_engine import get_code33_data, _fmp_fetch_revenue_ni
fmp_data = _fmp_fetch_revenue_ni('COST')
print("FMP Data lengths:", [len(x) if x else 0 for x in fmp_data[:4]])
d = get_code33_data('COST', 1)
print("COST result:", d.get('status'), d.get('sources'))
