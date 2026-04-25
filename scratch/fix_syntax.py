import re

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix _build_margin_pool
content = content.replace(
    'def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end, fy_end_m=12,\n                       edgar_rev, edgar_rev_end, edgar_ni, edgar_ni_end):',
    'def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,\n                       edgar_rev, edgar_rev_end, edgar_ni, edgar_ni_end, fy_end_m=12):'
)

# Also check _date_first_yoy if it has the same issue.
# def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends, fmp_fy=None, fmp_fp=None, edgar_fy=None, edgar_fp=None, fy_end_m=12):
# Since all parameters after fmp_ends have defaults, adding fy_end_m=12 at the end is perfectly fine!

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed Syntax Error')
