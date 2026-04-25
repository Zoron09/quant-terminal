import re

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add _get_fq_fy globally before # ── SEC EDGAR
helper_code = '''
def _get_fq_fy(dt, fy_end_m=12) -> str:
    try:
        shift = 12 - fy_end_m
        shifted_m = dt.month + shift
        if shifted_m > 12:
            fy = dt.year + 1
            shifted_m -= 12
        else:
            fy = dt.year
        fq = (shifted_m + 2) // 3
        return f"Q{fq} {fy}"
    except Exception:
        return ""

# ── SEC EDGAR'''
content = content.replace('# ── SEC EDGAR', helper_code, 1)

# 2. Add fy_end_month extraction in get_code33_data
target_info = '''        info = yf.Ticker(ticker.upper()).info or {}

        currency = str(info.get('currency', '')).upper()'''
replacement_info = '''        info = yf.Ticker(ticker.upper()).info or {}

        fy_end_month = 12
        if 'lastFiscalYearEnd' in info:
            try:
                from datetime import datetime, timezone
                fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
                fy_end_month = fy_end_dt.month
            except Exception:
                pass

        currency = str(info.get('currency', '')).upper()'''
content = content.replace(target_info, replacement_info, 1)

# 3. Update signatures of _date_first_yoy and _build_margin_pool
content = content.replace('def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,', 'def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end, fy_end_m=12,')
content = content.replace('def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends, fmp_fy=None, fmp_fp=None, edgar_fy=None, edgar_fp=None):', 'def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends, fmp_fy=None, fmp_fp=None, edgar_fy=None, edgar_fp=None, fy_end_m=12):')

# 4. Update the calls in get_code33_data
content = content.replace('_date_first_yoy(fmp_rev, fmp_rev_end, edgar_rev, edgar_rev_end, fmp_rev_fy, fmp_rev_fp, None, None)', '_date_first_yoy(fmp_rev, fmp_rev_end, edgar_rev, edgar_rev_end, fmp_rev_fy, fmp_rev_fp, None, None, fy_end_m=fy_end_month)')
content = content.replace('npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(', 'npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(fy_end_m=fy_end_month,')
content = content.replace('_date_first_yoy(\\n        fmp_eps, fmp_eps_end, edgar_eps, edgar_eps_end, fmp_eps_fy, fmp_eps_fp, None, None)', '_date_first_yoy(\\n        fmp_eps, fmp_eps_end, edgar_eps, edgar_eps_end, fmp_eps_fy, fmp_eps_fp, None, None, fy_end_m=fy_end_month)')
content = content.replace('eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(', 'eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\\n        fy_end_m=fy_end_month,')

# 5. Replace label generation string
content = re.sub(r'f"Q\{\(d_dt\.month \+ 2\) // 3\} \{d_dt\.year\}"', '_get_fq_fy(d_dt, fy_end_m)', content)
content = re.sub(r'f"Q\{\(curr_dt\.month \+ 2\) // 3\} \{curr_dt\.year\}"', '_get_fq_fy(curr_dt, fy_end_m)', content)
content = re.sub(r'f"Q\{\(d\.month \+ 2\)//3\} \{d\.year\}"', '_get_fq_fy(d, fy_end_month)', content)
content = re.sub(r'f"Q\{\(r\[\'dt\'\]\.month \+ 2\)//3\} \{r\[\'dt\'\]\.year\}"', '_get_fq_fy(r[\'dt\'], fy_end_month)', content)
content = re.sub(r'f"Q\{\(e\[\'dt\'\]\.month \+ 2\) // 3\} \{e\[\'dt\'\]\.year\}"', '_get_fq_fy(e[\'dt\'], fy_end_month)', content)
content = re.sub(r'f"Q\{\(item\[\'_end_dt\'\]\.month \+ 2\) // 3\} \{item\[\'_end_dt\'\]\.year\}"', '_get_fq_fy(item[\'_end_dt\'], fy_end_month)', content)

with open(r'C:\Users\Meet Singh\quant-terminal\pages\15_stock_detail.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
