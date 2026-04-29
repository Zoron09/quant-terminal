import sys
import importlib
sys.path.insert(0, r'C:\Users\Meet Singh\quant-terminal')
import streamlit as st
st.cache_data.clear()
mod = importlib.import_module('pages.15_stock_detail')

res = mod.get_code33_data('UCTT')
print('Sources:', res['sources'])
print('EPS:', res['eps'])
print('YOY:', mod._compute_yoy(res['eps']))

print("-----")
facts = mod.get_edgar_facts("UCTT")
if facts:
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    entries = usgaap.get('EarningsPerShareDiluted', {}).get('units', {}).get('USD/shares', [])
    filtered = [e for e in entries if e.get('form') == '10-Q']
    by_end = {}
    for e in filtered:
        end = e.get('end', '')
        if end not in by_end or e.get('filed', '') > by_end[end].get('filed', ''):
            by_end[end] = e
    sorted_items = sorted(by_end.items())
    recent = [float(v['val']) for _, v in sorted_items[-8:]]
    print("Recent 8 EPS:", recent)
    valid = [v for v in recent if v is not None and v != 0]
    import statistics
    med = abs(statistics.median(valid))
    print("Median:", med, "15x:", 15*med)
