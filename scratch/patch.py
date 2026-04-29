import sys

with open('utils/code33_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("CACHE_VERSION = 'v12'", "CACHE_VERSION = 'v13'")

search_def = "def _edgar_metric(concepts, unit='USD'):"
replace_def = "def _edgar_metric(concepts, unit='USD', is_eps=False):"
content = content.replace(search_def, replace_def)

search_loop = """                cloned['form'] = form

                if 80 <= duration_days <= 105:"""

replace_loop = """                cloned['form'] = form

                if is_eps and not (75 <= duration_days <= 105):
                    continue

                if 75 <= duration_days <= 105:"""
content = content.replace(search_loop, replace_loop)

search_call = """    edgar_eps, edgar_eps_lbl, edgar_eps_end, edgar_eps_fy, edgar_eps_fp = _edgar_metric(

        eps_keys_edgar, unit='USD/shares'

    )"""
replace_call = """    edgar_eps, edgar_eps_lbl, edgar_eps_end, edgar_eps_fy, edgar_eps_fp = _edgar_metric(

        eps_keys_edgar, unit='USD/shares', is_eps=True

    )"""
content = content.replace(search_call, replace_call)

with open('utils/code33_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)
