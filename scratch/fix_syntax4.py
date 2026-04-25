import re

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix line 1644 syntax error
content = content.replace(
    'eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\\n        fy_end_m=fy_end_month,\n\n            eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end, None, None, fmp_eps_fy, fmp_eps_fp\n\n        )',
    'eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\n            eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end, None, None, fmp_eps_fy, fmp_eps_fp, fy_end_m=fy_end_month\n        )'
)

# And fix line 1636 syntax
content = content.replace(
    'eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals = _date_first_yoy(\n        eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end, None, None, None, None\n    )',
    'eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals = _date_first_yoy(\n        eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end, None, None, None, None, fy_end_m=fy_end_month\n    )'
)

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed eps_yoy calls')
