"""
Patch: Add sector exclusion, gap flag, and negative base flag to Code 33.
Run with: python apply_c33_patch2.py
"""
import pathlib, sys

path = pathlib.Path('pages/15_stock_detail.py')
src  = path.read_text(encoding='utf-8')
lines = src.splitlines(keepends=True)

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 1 — Sector exclusion in get_code33_data()
# Anchor: the is_us block at the top of get_code33_data
# ══════════════════════════════════════════════════════════════════════════════
OLD_IS_US = (
    "    # \u2500\u2500 Pre-check currency (non-USD => NOT APPLICABLE downstream) \u2500\u2500\u2500\u2500\u2500\n"
    "    is_us = True\n"
    "    try:\n"
    "        info = yf.Ticker(ticker.upper()).info or {}\n"
    "        currency = str(info.get('currency', '')).upper()\n"
    "        if currency and currency != 'USD':\n"
    "            is_us = False\n"
    "    except Exception:\n"
    "        is_us = True\n"
    "\n"
    "    sources = {}"
)

NEW_IS_US = (
    "    # -- Pre-check currency + sector exclusion ----------------------------\n"
    "    is_us = True\n"
    "    sector_excluded = False\n"
    "    excluded_sector_name = ''\n"
    "    try:\n"
    "        info = yf.Ticker(ticker.upper()).info or {}\n"
    "        currency = str(info.get('currency', '')).upper()\n"
    "        if currency and currency != 'USD':\n"
    "            is_us = False\n"
    "        # Sector exclusion: REITs, Financials, Utilities, Cyclicals, Airlines\n"
    "        sector   = str(info.get('sector',   '') or '').strip()\n"
    "        industry = str(info.get('industry', '') or '').strip()\n"
    "        _EXCL_SECTORS = {'Real Estate', 'Financial Services', 'Utilities'}\n"
    "        _EXCL_INDUSTRY_KEYWORDS = [\n"
    "            'bank', 'insurance', 'asset management', 'reit', 'mortgage',\n"
    "            'steel', 'aluminum', 'auto manufacturer', 'automobile',\n"
    "            'paper', 'packaging', 'chemical', 'fertilizer',\n"
    "            'airline', 'air freight', 'airports',\n"
    "        ]\n"
    "        if sector in _EXCL_SECTORS:\n"
    "            sector_excluded = True\n"
    "            excluded_sector_name = sector\n"
    "        else:\n"
    "            ind_lower = industry.lower()\n"
    "            for kw in _EXCL_INDUSTRY_KEYWORDS:\n"
    "                if kw in ind_lower:\n"
    "                    sector_excluded = True\n"
    "                    excluded_sector_name = industry\n"
    "                    break\n"
    "    except Exception:\n"
    "        is_us = True\n"
    "\n"
    "    sources = {}"
)

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 — Return sector_excluded in the dict at end of get_code33_data
# ══════════════════════════════════════════════════════════════════════════════
OLD_RETURN = "        'sources': sources, 'is_us': is_us,\n"
NEW_RETURN  = "        'sources': sources, 'is_us': is_us,\n        'sector_excluded': sector_excluded, 'excluded_sector_name': excluded_sector_name,\n"

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 3 — _date_first_yoy: also return prior_vals list (for negative base flag)
# ══════════════════════════════════════════════════════════════════════════════
OLD_DFYOY_APPEND = (
    "        rates.append(rate)\n"
    "        labels.append(label)\n"
    "        ends_out.append(curr['end'])\n"
    "    # Sort chronologically (oldest first)\n"
    "    combined = sorted(zip(ends_out, rates, labels), key=lambda x: x[0])\n"
    "    if combined:\n"
    "        ends_out, rates, labels = zip(*combined)\n"
    "        return list(rates), list(labels), list(ends_out)\n"
    "    return [], [], []"
)
NEW_DFYOY_APPEND = (
    "        rates.append(rate)\n"
    "        labels.append(label)\n"
    "        ends_out.append(curr['end'])\n"
    "        prior_vals.append(prior['val'])  # track prior-year value for negative-base flag\n"
    "    # Sort chronologically (oldest first)\n"
    "    combined = sorted(zip(ends_out, rates, labels, prior_vals), key=lambda x: x[0])\n"
    "    if combined:\n"
    "        ends_out, rates, labels, prior_vals = zip(*combined)\n"
    "        return list(rates), list(labels), list(ends_out), list(prior_vals)\n"
    "    return [], [], [], []"
)
# Also need to add prior_vals = [] initialisation right before the rates/labels/ends_out init
OLD_DFYOY_INIT = (
    "    rates, labels, ends_out = [], [], []\n"
    "    seen_ends = set()  # avoid duplicate rate entries for same date"
)
NEW_DFYOY_INIT = (
    "    rates, labels, ends_out, prior_vals = [], [], [], []\n"
    "    seen_ends = set()  # avoid duplicate rate entries for same date"
)

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 4 — Fix all 6 callers of _date_first_yoy to unpack 4 values
# ══════════════════════════════════════════════════════════════════════════════
# Caller 1: Revenue YoY (returns _ for ends)
OLD_REV_YOY = "    rev_yoy_final, rev_labels_final, _ = _date_first_yoy(\n"
NEW_REV_YOY  = "    rev_yoy_final, rev_labels_final, _, _rev_prior_vals = _date_first_yoy(\n"
# Caller 2: EPS Pass 1
OLD_EPS1 = "    eps_yoy_final, eps_labels_final, eps_yoy_ends = _date_first_yoy(\n        eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end\n    )\n"
NEW_EPS1  = "    eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals = _date_first_yoy(\n        eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end\n    )\n"
# Caller 3: EPS Pass 2
OLD_EPS2 = "        eps_yoy_e2, eps_labels_e2, eps_ends_e2 = _date_first_yoy(\n            eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end\n        )\n        if len(eps_yoy_e2) > len(eps_yoy_final):\n            eps_yoy_final    = eps_yoy_e2\n            eps_labels_final = eps_labels_e2\n            eps_yoy_ends     = eps_ends_e2\n"
NEW_EPS2  = "        eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(\n            eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end\n        )\n        if len(eps_yoy_e2) > len(eps_yoy_final):\n            eps_yoy_final    = eps_yoy_e2\n            eps_labels_final = eps_labels_e2\n            eps_yoy_ends     = eps_ends_e2\n            eps_prior_vals   = eps_prior_e2\n"

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 5 — Also add eps_prior_vals to the return dict
# ══════════════════════════════════════════════════════════════════════════════
OLD_RETURN2 = "        'sources': sources, 'is_us': is_us,\n        'sector_excluded': sector_excluded, 'excluded_sector_name': excluded_sector_name,\n"
NEW_RETURN2  = "        'sources': sources, 'is_us': is_us,\n        'sector_excluded': sector_excluded, 'excluded_sector_name': excluded_sector_name,\n        'eps_prior_vals': eps_prior_vals if eps_yoy_final else [],\n"

# ══════════════════════════════════════════════════════════════════════════════
# Apply patches
# ══════════════════════════════════════════════════════════════════════════════
def check_and_apply(src, old, new, label):
    # Normalise line endings for matching
    src_n  = src.replace('\r\n', '\n')
    old_n  = old.replace('\r\n', '\n')
    if old_n not in src_n:
        print(f"  MISS: {label}")
        return src
    src_n = src_n.replace(old_n, new.replace('\r\n', '\n'), 1)
    print(f"  OK:   {label}")
    # Restore CRLF if original used it
    if '\r\n' in src:
        src_n = src_n.replace('\n', '\r\n')
    return src_n

src = check_and_apply(src, OLD_IS_US,          NEW_IS_US,          "Sector exclusion (is_us block)")
src = check_and_apply(src, OLD_RETURN,          NEW_RETURN,         "Return sector_excluded")
src = check_and_apply(src, OLD_DFYOY_INIT,      NEW_DFYOY_INIT,     "_date_first_yoy prior_vals init")
src = check_and_apply(src, OLD_DFYOY_APPEND,    NEW_DFYOY_APPEND,   "_date_first_yoy prior_vals append")
src = check_and_apply(src, OLD_REV_YOY,         NEW_REV_YOY,        "Revenue YoY caller")
src = check_and_apply(src, OLD_EPS1,            NEW_EPS1,           "EPS Pass 1 caller")
src = check_and_apply(src, OLD_EPS2,            NEW_EPS2,           "EPS Pass 2 caller")
src = check_and_apply(src, OLD_RETURN2,         NEW_RETURN2,        "Return eps_prior_vals")

path.write_text(src, encoding='utf-8')
print("\nPatch 1-5 done. Now patching render site (Tab 4)...")
# ══════════════════════════════════════════════════════════════════════════════
# PATCH 6 — Tab 4 render site:
#   a) Read sector_excluded from c33 dict
#   b) Overall status: force not_applicable when sector_excluded
#   c) Gap flag detection
#   d) Negative base flag
#   Anchor: the c33 fetch block
# ══════════════════════════════════════════════════════════════════════════════
src = path.read_text(encoding='utf-8')
src_n = src.replace('\r\n', '\n')

# 6a — unpack sector_excluded after c33 fetch
OLD_UNPACK = (
    "    eps_raw = c33.get('eps', [])\n"
    "    rev_raw = c33.get('rev', [])\n"
    "    ni_raw  = c33.get('ni',  [])\n"
    "    sources = c33.get('sources', {})\n"
    "    is_us   = c33.get('is_us', True)\n"
    "    eps_labels = c33.get('eps_labels', [])\n"
    "    rev_labels = c33.get('rev_labels', [])\n"
    "    npm_raw    = c33.get('npm', [])\n"
    "    npm_labels = c33.get('npm_labels', [])\n"
    "    npm_ends   = c33.get('npm_ends', [])\n"
)
NEW_UNPACK = (
    "    eps_raw = c33.get('eps', [])\n"
    "    rev_raw = c33.get('rev', [])\n"
    "    ni_raw  = c33.get('ni',  [])\n"
    "    sources = c33.get('sources', {})\n"
    "    is_us   = c33.get('is_us', True)\n"
    "    sector_excluded      = c33.get('sector_excluded', False)\n"
    "    excluded_sector_name = c33.get('excluded_sector_name', '')\n"
    "    eps_prior_vals = c33.get('eps_prior_vals', [])\n"
    "    eps_labels = c33.get('eps_labels', [])\n"
    "    rev_labels = c33.get('rev_labels', [])\n"
    "    npm_raw    = c33.get('npm', [])\n"
    "    npm_labels = c33.get('npm_labels', [])\n"
    "    npm_ends   = c33.get('npm_ends', [])\n"
)

# 6b — add sector_excluded to the overall status check
OLD_OVERALL = (
    "    # \u2500\u2500 Determine overall status \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "    if is_preprofit or not is_us:\n"
    "        overall = 'not_applicable'\n"
)
NEW_OVERALL = (
    "    # \u2500\u2500 Determine overall status \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "    if is_preprofit or not is_us or sector_excluded:\n"
    "        overall = 'not_applicable'\n"
)

# 6c — update NOT APPLICABLE message block to include sector exclusion
OLD_NA_MSG = (
    "    # Custom messages for NOT APPLICABLE\n"
    "    if overall == 'not_applicable':\n"
    "        if is_preprofit:\n"
    "            bn = f\"Code 33 requires accelerating positive earnings. {ticker} is pre-profit.\"\n"
    "        elif not is_us:\n"
    "            bn = f\"Code 33 uses SEC EDGAR data. {ticker} is a non-US company — limited data available.\"\n"
)
NEW_NA_MSG = (
    "    # Custom messages for NOT APPLICABLE\n"
    "    if overall == 'not_applicable':\n"
    "        if sector_excluded:\n"
    "            bn = f\"Sector excluded — Code 33 does not apply to {excluded_sector_name or ticker}. REITs, Financials, Utilities, Cyclicals and Airlines are excluded.\"\n"
    "        elif is_preprofit:\n"
    "            bn = f\"Code 33 requires accelerating positive earnings. {ticker} is pre-profit.\"\n"
    "        elif not is_us:\n"
    "            bn = f\"Code 33 uses SEC EDGAR data. {ticker} is a non-US company — limited data available.\"\n"
)

# 6d — Add gap flag + negative base detection AFTER the main badge st.markdown, before the card section
OLD_AFTER_BADGE = (
    "    # \u2500\u2500 3 side-by-side cards \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "    def _c33_card(title, rates3, d1, d2, status, unit='%', labels3=None, note=None):\n"
)
NEW_AFTER_BADGE = (
    "    # -- Gap flag: detect non-consecutive quarters in EPS or Revenue ------\n"
    "    def _has_gap(ends_list):\n"
    "        \"\"\"Return True if any two consecutive end dates are > 95 days apart (skipped quarter).\"\"\"\n"
    "        if len(ends_list) < 2:\n"
    "            return False\n"
    "        try:\n"
    "            dts = [datetime.strptime(e, '%Y-%m-%d').date() for e in ends_list]\n"
    "            return any(abs((dts[i+1] - dts[i]).days) > 95 for i in range(len(dts)-1))\n"
    "        except Exception:\n"
    "            return False\n"
    "\n"
    "    _eps_ends3  = c33.get('eps_end_dates', [])[-3:] if len(c33.get('eps_end_dates', [])) >= 3 else []\n"
    "    _rev_ends3  = c33.get('rev_end_dates', [])[-3:] if len(c33.get('rev_end_dates', [])) >= 3 else []\n"
    "    gap_detected = _has_gap(_eps_ends3) or _has_gap(_rev_ends3)\n"
    "\n"
    "    if gap_detected and overall not in ('not_applicable', 'insufficient'):\n"
    "        st.markdown(\n"
    "            f'<div style=\"background:#1a1200;border:1px solid {YELLOW};border-radius:6px;'\n"
    "            f'padding:10px 16px;margin-bottom:12px;font-size:12px;color:{YELLOW};\">'\n"
    "            f'<b>&#9888; WARNING</b> — Non-consecutive quarters detected. '\n"
    "            f'The YoY calculation may span a period gap. Results may be unreliable.</div>',\n"
    "            unsafe_allow_html=True\n"
    "        )\n"
    "\n"
    "    # -- Negative base flag: which EPS quarters had a negative prior-year val\n"
    "    _eps_prior3 = eps_prior_vals[-3:] if len(eps_prior_vals) >= 3 else eps_prior_vals\n"
    "    eps_distorted_base = [v is not None and v < 0 for v in _eps_prior3]\n"
    "\n"
    "    # \u2500\u2500 3 side-by-side cards \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "    def _c33_card(title, rates3, d1, d2, status, unit='%', labels3=None, note=None, distorted_bases=None):\n"
)

# 6e — Update _c33_card body to use distorted_bases for flagging row labels
OLD_CARD_BODY = (
    "            l1 = f'Q-2 ({labels3[0]})' if labels3 and len(labels3) > 0 else 'Q-2 (oldest)'\n"
    "            l2 = f'Q-1 ({labels3[1]})' if labels3 and len(labels3) > 1 else 'Q-1'\n"
    "            l3 = f'Q0 ({labels3[2]})' if labels3 and len(labels3) > 2 else 'Q0 (latest)'\n"
    "            body = (_qrow(l1, g1, is_first=True) +\n"
    "                    _qrow(l2, g2, delta=d1) +\n"
    "                    _qrow(l3, g3, delta=d2))\n"
)
NEW_CARD_BODY = (
    "            db = distorted_bases or [False, False, False]\n"
    "            def _db_tag(i): return ' <span style=\"color:#FF4444;font-size:9px\">[Distorted Base]</span>' if (len(db) > i and db[i]) else ''\n"
    "            l1 = (f'Q-2 ({labels3[0]})' if labels3 and len(labels3) > 0 else 'Q-2 (oldest)') + _db_tag(0)\n"
    "            l2 = (f'Q-1 ({labels3[1]})' if labels3 and len(labels3) > 1 else 'Q-1')           + _db_tag(1)\n"
    "            l3 = (f'Q0 ({labels3[2]})'  if labels3 and len(labels3) > 2 else 'Q0 (latest)')   + _db_tag(2)\n"
    "            body = (_qrow(l1, g1, is_first=True) +\n"
    "                    _qrow(l2, g2, delta=d1) +\n"
    "                    _qrow(l3, g3, delta=d2))\n"
)

# 6f — Pass distorted_bases when calling _c33_card for eps in normal mode
OLD_CARD_CALL = (
    "        card_col1.markdown(_c33_card(\"EPS Growth YoY%\",     eps3, eps_d1, eps_d2, eps_status, labels3=eps_labels3), unsafe_allow_html=True)\n"
)
NEW_CARD_CALL = (
    "        card_col1.markdown(_c33_card(\"EPS Growth YoY%\",     eps3, eps_d1, eps_d2, eps_status, labels3=eps_labels3, distorted_bases=eps_distorted_base), unsafe_allow_html=True)\n"
)

for old, new, label in [
    (OLD_UNPACK,       NEW_UNPACK,       "Unpack sector_excluded + eps_prior_vals"),
    (OLD_OVERALL,      NEW_OVERALL,      "sector_excluded -> not_applicable"),
    (OLD_NA_MSG,       NEW_NA_MSG,       "NOT APPLICABLE sector message"),
    (OLD_AFTER_BADGE,  NEW_AFTER_BADGE,  "Gap flag + negative base detection"),
    (OLD_CARD_BODY,    NEW_CARD_BODY,    "_c33_card distorted base row labels"),
    (OLD_CARD_CALL,    NEW_CARD_CALL,    "_c33_card eps call with distorted_bases"),
]:
    src = check_and_apply(src, old, new, label)

path.write_text(src, encoding='utf-8')
print("\nAll patches applied.")
