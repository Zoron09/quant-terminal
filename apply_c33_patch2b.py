"""Apply the 3 missed patches from patch2 — using index/line-based matching."""
import pathlib

path = pathlib.Path('pages/15_stock_detail.py')
src = path.read_text(encoding='utf-8').replace('\r\n', '\n')

# ── MISS 1: Sector exclusion (is_us block) ────────────────────────────────────
# Find the is_us block inside get_code33_data by anchoring on unique neighbour lines
OLD1 = (
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
NEW1 = (
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
if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    print("OK:   MISS1 - sector exclusion")
else:
    print("FAIL: MISS1 - is_us block not found")

# ── MISS 2: sector_excluded -> not_applicable in overall status ───────────────
OLD2 = "    if is_preprofit or not is_us:\n        overall = 'not_applicable'\n"
NEW2 = "    if is_preprofit or not is_us or sector_excluded:\n        overall = 'not_applicable'\n"
if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    print("OK:   MISS2 - overall status sector_excluded")
else:
    print("FAIL: MISS2 - overall status block not found")

# ── MISS 3: Gap flag + negative base block before the 3 cards ─────────────────
# Anchor: the unique _c33_card function signature (which was already updated to add distorted_bases)
OLD3 = (
    "    def _c33_card(title, rates3, d1, d2, status, unit='%', labels3=None, note=None, distorted_bases=None):\n"
)
GAP_BLOCK = (
    "    # -- Gap flag: detect non-consecutive quarters in EPS or Revenue ------\n"
    "    def _has_gap(ends_list):\n"
    "        \"\"\"Return True if any two consecutive end dates are > 95 days apart.\"\"\"\n"
    "        if len(ends_list) < 2:\n"
    "            return False\n"
    "        try:\n"
    "            dts = [datetime.strptime(e, '%Y-%m-%d').date() for e in ends_list]\n"
    "            return any(abs((dts[i+1] - dts[i]).days) > 95 for i in range(len(dts)-1))\n"
    "        except Exception:\n"
    "            return False\n"
    "\n"
    "    _eps_ends3 = c33.get('eps_end_dates', [])[-3:] if len(c33.get('eps_end_dates', [])) >= 3 else []\n"
    "    _rev_ends3 = c33.get('rev_end_dates', [])[-3:] if len(c33.get('rev_end_dates', [])) >= 3 else []\n"
    "    gap_detected = _has_gap(_eps_ends3) or _has_gap(_rev_ends3)\n"
    "\n"
    "    if gap_detected and overall not in ('not_applicable', 'insufficient'):\n"
    "        st.markdown(\n"
    "            f'<div style=\"background:#1a1200;border:1px solid {YELLOW};border-radius:6px;'\n"
    "            f'padding:10px 16px;margin-bottom:12px;font-size:12px;color:{YELLOW};\">'\n"
    "            f'<b>&#9888; WARNING</b> \u2014 Non-consecutive quarters detected. '\n"
    "            f'The YoY calculation may span a period gap. Results may be unreliable.</div>',\n"
    "            unsafe_allow_html=True\n"
    "        )\n"
    "\n"
    "    # -- Negative base flag: which EPS quarters had a negative prior-year value\n"
    "    _eps_prior3 = eps_prior_vals[-3:] if len(eps_prior_vals) >= 3 else eps_prior_vals\n"
    "    eps_distorted_base = [v is not None and v < 0 for v in _eps_prior3]\n"
    "\n"
)
NEW3 = GAP_BLOCK + OLD3
if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    print("OK:   MISS3 - gap flag + negative base block")
else:
    print("FAIL: MISS3 - _c33_card definition not found")

path.write_text(src.replace('\n', '\r\n'), encoding='utf-8')  # restore CRLF
print("\nDone.")
