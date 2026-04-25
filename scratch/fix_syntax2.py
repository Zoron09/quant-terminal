import re

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix _build_margin_pool keyword arg issue
content = content.replace(
    'npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(fy_end_m=fy_end_month,\n\n        fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,\n\n        edgar_rev, edgar_rev_end, edgar_ni_abs, edgar_ni_end\n\n    )',
    'npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(\n\n        fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,\n\n        edgar_rev, edgar_rev_end, edgar_ni_abs, edgar_ni_end, fy_end_m=fy_end_month\n\n    )'
)

content = content.replace(
    'eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\n        fy_end_m=fy_end_month,\n        edgar_eps, edgar_eps_end, fmp_eps, fmp_eps_end, None, None, fmp_eps_fy, fmp_eps_fp\n    )',
    'eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\n        edgar_eps, edgar_eps_end, fmp_eps, fmp_eps_end, None, None, fmp_eps_fy, fmp_eps_fp, fy_end_m=fy_end_month\n    )'
)

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed Syntax Error 2')
