import os
import sys
import logging
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import streamlit as st
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Load env vars from root .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from utils.sec_edgar import get_cik

try:
    from utils.edgar_revenue import get_quarterly_revenue
    _HAS_EDGARTOOLS_REV = True
except Exception:
    _HAS_EDGARTOOLS_REV = False

try:
    from utils.edgar_net_margin import get_quarterly_net_margin
    _HAS_EDGARTOOLS_MARGIN = True
except Exception:
    _HAS_EDGARTOOLS_MARGIN = False

try:
    from utils.secfs_revenue import get_quarterly_revenue as get_quarterly_revenue_secfs
    _HAS_SECFS_REV = True
except Exception:
    _HAS_SECFS_REV = False

try:
    from utils.secfs_net_margin import get_quarterly_net_margin as get_quarterly_net_margin_secfs
    _HAS_SECFS_MARGIN = True
except Exception:
    _HAS_SECFS_MARGIN = False

# ── API keys ──────────────────────────────────────────────────────────────────
FMP_API_KEY = os.getenv('FMP_API_KEY', '')
_HAS_FMP    = bool(FMP_API_KEY)

try:
    from utils.finnhub_client import FINNHUB_KEY
    _HAS_FINNHUB = bool(FINNHUB_KEY)
except Exception:
    FINNHUB_KEY  = ''
    _HAS_FINNHUB = False

CACHE_VERSION = 'v29'

# ── SEC EDGAR headers ─────────────────────────────────────────────────────────
EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

# ── Small numeric helpers ─────────────────────────────────────────────────────
def _nan(v):
    if v is None: return True
    try: return isinstance(v, float) and np.isnan(v)
    except Exception: return False

def _sf(v, default=None):
    if _nan(v): return default
    try: return float(v)
    except Exception: return default

# ── SEC EDGAR facts fetcher ───────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def get_edgar_facts(ticker: str, cache_v: str = CACHE_VERSION) -> dict | None:
    if '.' in ticker: return None
    cik = get_cik(ticker)
    if not cik: return None
    try:
        r = requests.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
                         headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def _edgar_series(facts: dict | None, concepts: list, unit: str = 'USD',
                  quarterly: bool = True, balance: bool = False) -> dict:
    """Returns {end_date: float} sorted ascending (oldest first), max 8 most recent entries."""
    if not facts: return {}
    usgaap = facts.get('facts', {}).get('us-gaap', {})
    for concept in concepts:
        entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
        if not entries: continue
        if quarterly or balance:
            filtered = [e for e in entries if e.get('form') == '10-Q']
        else:
            filtered = [e for e in entries if e.get('form') == '10-K']
        if len(filtered) < 3: continue
        by_end: dict = {}
        for e in filtered:
            end = e.get('end', '')
            if not end: continue
            if end not in by_end or e.get('filed', '') > by_end[end].get('filed', ''):
                by_end[end] = e
        if len(by_end) >= 3:
            sorted_items = sorted(by_end.items())
            recent_8 = sorted_items[-8:]
            return {end: float(v['val']) for end, v in recent_8}
    return {}


def _get_fq_fy(dt, fy_end_m=12) -> str:
    try:
        if dt.month in (3, 6, 9, 12):
            return f"Q{dt.month // 3} {dt.year}"
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

def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,

                       edgar_rev, edgar_rev_end, edgar_ni, edgar_ni_end, fy_end_m=12):

    """Build chronological net-profit-margin series (NI/Rev per quarter).

    Strict source lock: FMP-rev must pair with FMP-ni, EDGAR-rev with EDGAR-ni.

    Returns (margins, labels, ends) in chronological order (oldest first)."""

    fmp_rev_map   = {e: float(v) for v, e in zip(fmp_rev   or [], fmp_rev_end   or []) if v is not None and e}

    fmp_ni_map    = {e: float(v) for v, e in zip(fmp_ni    or [], fmp_ni_end    or []) if v is not None and e}

    edgar_rev_map = {e: float(v) for v, e in zip(edgar_rev or [], edgar_rev_end or []) if v is not None and e}

    edgar_ni_map  = {e: float(v) for v, e in zip(edgar_ni  or [], edgar_ni_end  or []) if v is not None and e}



    all_dates = sorted(set(

        list(fmp_rev_map.keys()) + list(fmp_ni_map.keys()) +

        list(edgar_rev_map.keys()) + list(edgar_ni_map.keys())

    ), reverse=True)



    deduped_dates = []

    for d in all_dates:

        duplicate = False

        for kept in deduped_dates:

            try:

                d1 = datetime.strptime(d,    '%Y-%m-%d').date()

                d2 = datetime.strptime(kept, '%Y-%m-%d').date()

                if abs((d1 - d2).days) <= 60:

                    duplicate = True

                    break

            except Exception:

                pass

        if not duplicate:

            deduped_dates.append(d)



    margins, margin_ends, margin_labels = [], [], []

    for d in deduped_dates[:8]:

        margin = None

        try:

            d_dt = datetime.strptime(d, '%Y-%m-%d').date()

        except Exception:

            continue



        # ── Source lock: FMP rev + FMP ni (same source, within 60 days) ──────

        fmp_rev_val = None

        fmp_ni_val  = None

        for fd in fmp_rev_map:

            try:

                if abs((d_dt - datetime.strptime(fd, '%Y-%m-%d').date()).days) <= 60:

                    fmp_rev_val = fmp_rev_map[fd]

                    break

            except Exception:

                pass

        if fmp_rev_val is not None:

            for fd in fmp_ni_map:

                try:

                    if abs((d_dt - datetime.strptime(fd, '%Y-%m-%d').date()).days) <= 60:

                        fmp_ni_val = fmp_ni_map[fd]

                        break

                except Exception:

                    pass



        if fmp_rev_val is not None and fmp_ni_val is not None and fmp_rev_val > 0:

            margin = (fmp_ni_val / fmp_rev_val) * 100

        else:

            # ── Source lock: EDGAR rev + EDGAR ni (never mixed with FMP) ─────

            edgar_rev_val = None

            edgar_ni_val  = None

            for ed in edgar_rev_map:

                try:

                    if abs((d_dt - datetime.strptime(ed, '%Y-%m-%d').date()).days) <= 60:

                        edgar_rev_val = edgar_rev_map[ed]

                        break

                except Exception:

                    pass

            if edgar_rev_val is not None:

                for ed in edgar_ni_map:

                    try:

                        if abs((d_dt - datetime.strptime(ed, '%Y-%m-%d').date()).days) <= 60:

                            edgar_ni_val = edgar_ni_map[ed]

                            break

                    except Exception:

                        pass

            if edgar_rev_val is not None and edgar_ni_val is not None and edgar_rev_val > 0:

                margin = (edgar_ni_val / edgar_rev_val) * 100



        margins.append(margin)

        margin_ends.append(d)

        try:

            label = _get_fq_fy(d_dt, fy_end_m)

        except Exception:

            label = d

        margin_labels.append(label)



    # Return in chronological order (oldest first)

    margins.reverse(); margin_ends.reverse(); margin_labels.reverse()

    return margins, margin_labels, margin_ends

def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends, fmp_fy=None, fmp_fp=None, edgar_fy=None, edgar_fp=None, fy_end_m=12, src_primary='FMP', src_fallback='EDGAR', append_none=False):
    """Calculate YoY growth using strict fiscal-period matching first, fallback to date matching.
    Prevents source-mixing and historical data deletion bugs."""

    def _make_pool(vals, ends, fys, fps, source_name):
        pool = []
        src_list = source_name if isinstance(source_name, list) else [source_name] * len(vals or [])
        for v, e, fy, fp, src in zip(vals or [], ends or [], fys or [None]*len(vals or []), fps or [None]*len(vals or []), src_list):
            if v is not None and e:
                pool.append({'val': float(v), 'end': e, 'fy': fy, 'fp': str(fp).strip().upper() if fp else None, 'source': src})
        pool.sort(key=lambda x: x['end'], reverse=True)
        deduped = []
        for entry in pool:
            duplicate = False
            for kept in deduped:
                try:
                    d1 = datetime.strptime(entry['end'], '%Y-%m-%d').date()
                    d2 = datetime.strptime(kept['end'],  '%Y-%m-%d').date()
                    if abs((d1 - d2).days) <= 60:
                        duplicate = True
                        break
                except Exception:
                    pass
            if not duplicate:
                deduped.append(entry)
        return deduped

    def _find_prior(curr, curr_dt, search_pool, i_hint=None):
        """Try date-proximity first, then fiscal-period fallback."""
        # 1. PRIMARY: Date proximity (abs(curr_end - cand_end - 365) <= 60 days)
        try:
            target_dt = curr_dt.replace(year=curr_dt.year - 1)
        except ValueError:
            target_dt = curr_dt - timedelta(days=365)
        best_diff = 61  # Max 60 days diff
        best_cand = None
        for cand in search_pool:
            if cand['end'] == curr['end']: continue
            try:
                cand_dt = datetime.strptime(cand['end'], '%Y-%m-%d').date()
                diff = abs((cand_dt - target_dt).days)
                if diff < best_diff:
                    best_diff = diff
                    best_cand = cand
            except Exception:
                pass
        if best_cand is not None:
            return best_cand

        # 2. FALLBACK: Strict Fiscal Period matching (Q4 -> Q4 of previous year)
        if curr['fy'] is not None and curr['fp'] in ('Q1', 'Q2', 'Q3', 'Q4'):
            target_fy = curr['fy'] - 1
            for cand in search_pool:
                if cand['end'] == curr['end']: continue
                if cand['fy'] == target_fy and cand['fp'] == curr['fp']:
                    return cand

        # 3. Sequential matching (+4 quarters) — only for same-source pool
        if i_hint is not None and i_hint + 4 < len(search_pool):
            seq_prior = search_pool[i_hint + 4]
            try:
                sq_dt = datetime.strptime(seq_prior['end'], '%Y-%m-%d').date()
                diff_months = (curr_dt - sq_dt).days / 30.4
                if 9 <= diff_months <= 15:
                    return seq_prior
            except Exception:
                pass

        return None

    def _yoy_for_src(deduped, fallback_pool=None):
        results = []
        seen = set()
        for i, curr in enumerate(deduped):
            if curr['end'] in seen: continue
            try:
                curr_dt = datetime.strptime(curr['end'], '%Y-%m-%d').date()
            except Exception:
                continue

            # Same-source first: fiscal → date → sequential
            prior = _find_prior(curr, curr_dt, deduped, i_hint=i)

            # Cross-source fallback: only when same-source has no prior within ±31d
            if prior is None and fallback_pool:
                prior = _find_prior(curr, curr_dt, fallback_pool, i_hint=None)

            if prior is None or prior['val'] == 0:
                if append_none:
                    try:
                        label = _get_fq_fy(curr_dt, fy_end_m)
                    except Exception:
                        label = curr['end']
                    seen.add(curr['end'])
                    results.append({
                        'dt': curr_dt, 'end': curr['end'], 'rate': None,
                        'label': label, 'prior_val': None, 'curr_val': curr['val'],
                        'source': curr.get('source', '')
                    })
                continue

            seen.add(curr['end'])
            rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100
            try:
                label = _get_fq_fy(curr_dt, fy_end_m)
            except Exception:
                label = curr['end']
            results.append({
                'dt': curr_dt, 'end': curr['end'], 'rate': rate,
                'label': label, 'prior_val': prior['val'], 'curr_val': curr['val'],
                'source': curr.get('source', '')
            })
        return results

    fmp_pool   = _make_pool(fmp_vals, fmp_ends, fmp_fy, fmp_fp, src_primary)
    edgar_pool = _make_pool(edgar_vals, edgar_ends, edgar_fy, edgar_fp, src_fallback)

    f_yoy = _yoy_for_src(fmp_pool, fallback_pool=edgar_pool)
    e_yoy = _yoy_for_src(edgar_pool, fallback_pool=fmp_pool)

    merged = list(f_yoy)
    for ey in e_yoy:
        duplicate_idx = -1
        for idx, fy in enumerate(merged):
            if abs((ey['dt'] - fy['dt']).days) <= 60:
                duplicate_idx = idx
                break
        if duplicate_idx == -1:
            merged.append(ey)
        else:
            fy = merged[duplicate_idx]
            curr_diff = abs(ey['curr_val'] - fy['curr_val']) / max(abs(ey['curr_val']), abs(fy['curr_val']), 1e-9)
            if ey['prior_val'] is not None and fy['prior_val'] is not None:
                prior_diff = abs(ey['prior_val'] - fy['prior_val']) / max(abs(ey['prior_val']), abs(fy['prior_val']), 1e-9)
            else:
                prior_diff = 0.0
            if curr_diff > 0.01 or prior_diff > 0.01:
                merged[duplicate_idx] = ey

    merged.sort(key=lambda x: x['dt'])
    if len(merged) > 16:
        merged = merged[-16:]
    if merged:
        return (
            [x['rate'] for x in merged],
            [x['label'] for x in merged],
            [x['end'] for x in merged],
            [x['prior_val'] for x in merged],
            [x.get('source', '') for x in merged]
        )
    return [], [], [], [], []

@st.cache_data(ttl=86400, show_spinner=False)

def get_code33_data(ticker: str, cache_v: str = CACHE_VERSION) -> dict:

    """Fetch EPS, Revenue, Net Margin independently for Code 33 analysis.

    EPS: Finnhub stock/earnings (adjusted) primary, EDGAR GAAP fill for missing quarters.

    Revenue + Net Margin: FMP quarterly income statement primary, EDGAR fallback.

    Need minimum 8 raw quarters per metric to compute 4 YoY rates (3 acceleration deltas)."""

    import yfinance as yf



    # ── Pre-check currency (non-USD => NOT APPLICABLE downstream) ─────────────

    is_us = True

    sector_excluded = False

    excluded_sector_name = ''

    fy_end_month = 12
    try:

        info = yf.Ticker(ticker.upper()).info or {}

        fy_end_month = 12
        if 'lastFiscalYearEnd' in info:
            try:
                from datetime import timezone
                fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
                m = fy_end_dt.month
                # January FY-end: treat as December so calendar-year quarters
                # don't shift into the NEXT fiscal year label
                # (e.g. GIII Oct 2025 → "Q3 2026" becomes "Q4 2025")
                fy_end_month = 12 if m == 1 else m
            except Exception:
                pass

        currency = str(info.get('currency', '')).upper()

        if currency and currency != 'USD':

            is_us = False

        # Sector exclusion logic (Minervini SEPA methodology):
        #   Hard exclusion  → NOT APPLICABLE (Utilities, Cyclicals, Airlines)
        #   Soft warning    → runs Code 33 but shows REIT advisory
        #   No exclusion    → Financials removed per Minervini (can be superperformance leaders)

        sector   = str(info.get('sector',   '') or '').strip()

        industry = str(info.get('industry', '') or '').strip()

        # Hard-excluded sectors: Utilities only at the sector level.
        # Financial Services deliberately removed — banks/brokers/fintechs can be leaders.
        _EXCL_SECTORS = {'Utilities'}

        # Hard-excluded industry keywords: Cyclicals + Airlines.
        # 'reit', 'bank', 'insurance', 'mortgage' removed from hard list.
        _EXCL_INDUSTRY_KEYWORDS = [

            'steel', 'aluminum', 'auto manufacturer', 'automobile',

            'paper', 'packaging', 'chemical', 'fertilizer',

            'airline', 'air freight', 'airports',

        ]

        # REIT soft-warning keywords (run Code 33, but show advisory)
        _REIT_KEYWORDS = ['reit', 'real estate investment trust']

        if sector in _EXCL_SECTORS:

            sector_excluded = True

            excluded_sector_name = sector

        else:

            ind_lower = industry.lower()

            for kw in _EXCL_INDUSTRY_KEYWORDS:

                if kw in ind_lower:

                    sector_excluded = True

                    excluded_sector_name = industry

                    break

        # Detect REIT for soft warning (sector='Real Estate' or industry keyword)
        is_reit = (
            sector == 'Real Estate' or
            any(kw in industry.lower() for kw in _REIT_KEYWORDS)
        )

    except Exception:

        is_us = True

        is_reit = False



    sources = {}







    def _fmp_fetch_revenue_ni(symbol: str):

        """Fetch quarterly revenue + net income + EPS from FMP income-statement endpoint.

        Covers ALL fiscal calendars including Q4 from 10-K filings.

        Returns (rev_vals, rev_lbls, rev_ends, rev_fy, rev_fp,

                 ni_vals, ni_lbls, ni_ends, ni_fy, ni_fp,

                 margin_vals, margin_lbls, margin_ends,

                 eps_vals, eps_lbls, eps_ends, eps_fy, eps_fp)."""

        _empty = [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []

        if not _HAS_FMP:

            return _empty

        try:

            r = requests.get(

                "https://financialmodelingprep.com/stable/income-statement",

                params={'symbol': symbol.upper(), 'period': 'quarter',

                        'limit': 12, 'apikey': FMP_API_KEY},

                timeout=10

            )

            r.raise_for_status()

            data = r.json() if isinstance(r.json(), list) else []

            if not data:

                return _empty



            # FMP returns newest first — sort descending, take 8, then reverse to ascending

            rows = []

            for item in data:

                if not isinstance(item, dict):

                    continue

                date_str = str(item.get('date', '')).strip()

                revenue = _sf(item.get('revenue'))

                net_income = _sf(item.get('netIncome'))

                eps_val = _sf(item.get('epsDiluted')) or _sf(item.get('eps'))

                fiscal_year = item.get('fiscalYear') or item.get('calendarYear')

                period = str(item.get('period', '')).upper().strip()

                if not date_str or revenue is None:

                    continue

                try:

                    dt = datetime.strptime(date_str, '%Y-%m-%d').date()

                    fy_int = int(fiscal_year) if fiscal_year is not None else None

                except Exception:

                    continue

                rows.append({'dt': dt, 'rev': float(revenue),

                             'ni': float(net_income) if net_income is not None else None,

                             'eps': float(eps_val) if eps_val is not None else None,

                             'fy': fy_int, 'fp': period if period in ('Q1','Q2','Q3','Q4') else None})



            if not rows:

                return _empty



            rows = sorted(rows, key=lambda x: x['dt'], reverse=True)[:12]

            rows.reverse()  # oldest first



            rev_vals = [r['rev'] for r in rows]

            rev_ends = [r['dt'].isoformat() for r in rows]

            rev_lbls = [_get_fq_fy(r['dt'], fy_end_month) for r in rows]

            rev_fy   = [r['fy']  for r in rows]

            rev_fp   = [r['fp']  for r in rows]



            # Net income absolute values

            ni_vals, ni_lbls, ni_ends, ni_fy, ni_fp = [], [], [], [], []

            for r in rows:

                if r['ni'] is not None:

                    ni_vals.append(r['ni'])

                    ni_lbls.append(_get_fq_fy(r['dt'], fy_end_month))

                    ni_ends.append(r['dt'].isoformat())

                    ni_fy.append(r['fy'])

                    ni_fp.append(r['fp'])



            # Compute quarterly margin % = netIncome / revenue * 100

            margin_vals, margin_lbls, margin_ends = [], [], []

            for r in rows:

                if r['ni'] is not None and r['rev'] != 0:

                    margin_vals.append(r['ni'] / r['rev'] * 100)

                    margin_lbls.append(_get_fq_fy(r['dt'], fy_end_month))

                    margin_ends.append(r['dt'].isoformat())



            # EPS (diluted preferred)

            eps_vals, eps_lbls, eps_ends, eps_fy, eps_fp = [], [], [], [], []

            for r in rows:

                if r['eps'] is not None:

                    eps_vals.append(r['eps'])

                    eps_lbls.append(_get_fq_fy(r['dt'], fy_end_month))

                    eps_ends.append(r['dt'].isoformat())

                    eps_fy.append(r['fy'])

                    eps_fp.append(r['fp'])



            return (rev_vals, rev_lbls, rev_ends, rev_fy, rev_fp,

                    ni_vals, ni_lbls, ni_ends, ni_fy, ni_fp,

                    margin_vals, margin_lbls, margin_ends,

                    eps_vals, eps_lbls, eps_ends, eps_fy, eps_fp)

        except Exception:

            return _empty



    def _is_recent(end_dates, max_days=548):

        """Reject data if most recent date is older than max_days (~18 months)."""

        if not end_dates:

            return False

        try:

            most_recent = max(datetime.strptime(d, '%Y-%m-%d').date() for d in end_dates)

            return (datetime.utcnow().date() - most_recent).days <= max_days

        except Exception:

            return False



    def _normalize_to_pool(entries_list):

        """

        Merge data points from multiple sources into one deduplicated pool.

        entries_list = list of (values, end_dates, source_name) tuples.

        Two entries are same quarter if end_dates within 60 days.

        Returns (values, labels, end_dates) sorted ascending, max 8 most recent.

        """

        pool = []

        for vals, ends, src in entries_list:

            for v, e in zip(vals, ends):

                if v is None or e is None:

                    continue

                try:

                    dt = datetime.strptime(e, '%Y-%m-%d').date()

                except Exception:

                    continue

                pool.append({'dt': dt, 'val': float(v), 'src': src})



        if not pool:

            return [], [], [], []



        # Deduplicate: for each quarter window, keep entry with latest dt

        # Sort by date descending, then deduplicate by 60-day proximity

        pool.sort(key=lambda x: x['dt'], reverse=True)

        deduped = []

        for entry in pool:

            duplicate = False

            for kept in deduped:

                if abs((entry['dt'] - kept['dt']).days) <= 60:

                    duplicate = True

                    break

            if not duplicate:

                deduped.append(entry)



        # Take 8 most recent, then reverse to ascending

        deduped = deduped[:8]

        deduped.reverse()



        vals = [e['val'] for e in deduped]

        ends = [e['dt'].isoformat() for e in deduped]

        lbls = [_get_fq_fy(e['dt'], fy_end_month) for e in deduped]

        srcs = [e['src'] for e in deduped]

        return vals, lbls, ends, srcs



    # _finnhub_is_recent replaced by _is_recent above (shared by FMP + Finnhub)



    def _is_implausible(derived_val, q_vals):
        if not q_vals: return False
        max_q = max(abs(v) for v in q_vals)
        if max_q < 10000: return False  # Skip for very small numbers to avoid zero-division noise

        avg_q = sum(abs(v) for v in q_vals) / len(q_vals)

        # FIX 1: Use avg_q (not max_q) for spike check.
        # max_q alone rejects legitimate Q4s in seasonal businesses where one quarter
        # dominates — e.g. a retailer with a massive Q3 will have a max_q >> avg_q.
        # Using 6x avg_q as spike threshold is more representative of true outliers.
        if avg_q > 0 and abs(derived_val) > 6 * avg_q:
            return True

        # FIX 4: Sign-flip check — only reject if sum_q is meaningfully non-zero.
        # Old logic: `sum_q != 0` fired even when Q vals nearly cancelled each other out
        # (e.g. Q1=+50M, Q2=-49M, Q3=+1M → sum_q=2M but nearly zero).
        # New logic: require abs(sum_q) > 0.1 * max_q so the sign comparison is stable.
        sum_q = sum(q_vals)
        if abs(sum_q) > 0.1 * max_q and (derived_val * sum_q) < 0:
            if abs(derived_val) > 2 * max_q:
                return True

        # Reject if suspiciously tiny — restatement artifact where annual was bumped
        # by a small amount and the remainder is assigned to Q4.
        if avg_q > 5000000 and abs(derived_val) < 0.15 * avg_q:
            return True

        return False

    # ── EDGAR fetcher (independent per metric) ────────────────────────────────
    def _edgar_metric(concepts, unit='USD', is_eps=False, is_revenue=False):
        """Return (values, labels, end_dates, fy_list, fp_list) from SEC EDGAR filings using strict quarterly filters."""
        facts = get_edgar_facts(ticker)
        if not facts:
            return [], [], [], [], [], []

        usgaap = facts.get('facts', {}).get('us-gaap', {})
        cutoff_date = (datetime.utcnow() - timedelta(days=365 * 5)).date()
        recency_cutoff = (datetime.utcnow() - timedelta(days=548)).date()  # ~18 months

        def _extract_for_concept(concept):
            global_dedup = {}
            global_ytd_6m = {}
            global_ytd_9m = {}
            global_annual = {}

            entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])
            if not entries:
                return []

            for e in entries:
                form = str(e.get('form', '')).strip().upper()
                if form not in ('10-Q', '10-K', '20-F', '6-K'):
                    continue
                end_str = str(e.get('end', '')).strip()
                start_str = str(e.get('start', '')).strip()
                val = _sf(e.get('val'))
                if not end_str or not start_str or val is None:
                    continue
                try:
                    end_dt = datetime.strptime(end_str, '%Y-%m-%d').date()
                    start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
                except Exception:
                    continue
                if end_dt < cutoff_date:
                    continue
                duration_days = (end_dt - start_dt).days
                end_key = e['end']
                cloned = dict(e)
                cloned['_end_dt'] = end_dt
                cloned['_val'] = float(val)
                cloned['_fy'] = int(e['fy']) if e.get('fy') is not None else end_dt.year
                cloned['_fp'] = str(e['fp']).strip().upper() if e.get('fp') else None
                cloned['form'] = form

                if is_eps and not (75 <= duration_days <= 105):
                    continue

                if 75 <= duration_days <= 105:
                    if end_key not in global_dedup:
                        global_dedup[end_key] = cloned
                    elif is_revenue and cloned['_val'] > global_dedup[end_key]['_val']:
                        global_dedup[end_key] = cloned
                    elif not is_revenue:
                        global_dedup[end_key] = cloned
                elif 170 <= duration_days <= 195:
                    if end_key not in global_ytd_6m:
                        global_ytd_6m[end_key] = cloned
                    elif is_revenue and cloned['_val'] > global_ytd_6m[end_key]['_val']:
                        global_ytd_6m[end_key] = cloned
                    elif not is_revenue:
                        global_ytd_6m[end_key] = cloned
                elif 260 <= duration_days <= 285:
                    if end_key not in global_ytd_9m:
                        global_ytd_9m[end_key] = cloned
                    elif is_revenue and cloned['_val'] > global_ytd_9m[end_key]['_val']:
                        global_ytd_9m[end_key] = cloned
                    elif not is_revenue:
                        global_ytd_9m[end_key] = cloned
                elif 335 <= duration_days <= 395:
                    if form in ('10-K', '20-F'):
                        annual_fy = int(e['fy']) if e.get('fy') is not None else None
                        if end_dt not in global_annual:
                            global_annual[end_dt] = (end_dt, start_dt, float(val), annual_fy)
                        elif is_revenue and float(val) > global_annual[end_dt][2]:
                            global_annual[end_dt] = (end_dt, start_dt, float(val), annual_fy)
                        elif not is_revenue:
                            global_annual[end_dt] = (end_dt, start_dt, float(val), annual_fy)

            for ytd_end, ytd_entry in global_ytd_6m.items():
                if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):
                    target_q1_end = ytd_entry['_end_dt'] - timedelta(days=90)
                    q1_entry = next((v for v in global_dedup.values() if abs((v['_end_dt'] - target_q1_end).days) <= 25), None)
                    if q1_entry:
                        derived_q2_val = ytd_entry['_val'] - q1_entry['_val']
                        if not _is_implausible(derived_q2_val, [q1_entry['_val']]):
                            derived_q2 = dict(ytd_entry)
                            derived_q2['_val'] = derived_q2_val
                            derived_q2['form'] = '10-Q-derived'
                            global_dedup[ytd_end] = derived_q2

            for ytd_end, ytd_entry in global_ytd_9m.items():
                if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):
                    target_q2_end = ytd_entry['_end_dt'] - timedelta(days=90)
                    ytd_6m_entry = next((v for v in global_ytd_6m.values() if abs((v['_end_dt'] - target_q2_end).days) <= 25), None)
                    if ytd_6m_entry:
                        derived_q3_val = ytd_entry['_val'] - ytd_6m_entry['_val']
                        if not _is_implausible(derived_q3_val, [ytd_6m_entry['_val'] / 2]):
                            derived_q3 = dict(ytd_entry)
                            derived_q3['_val'] = derived_q3_val
                            derived_q3['form'] = '10-Q-derived'
                            global_dedup[ytd_end] = derived_q3

            filtered_entries = sorted(global_dedup.values(), key=lambda x: x['_end_dt'], reverse=True)
            
            annual_entries = [(item[0], item[1], item[2], item[3]) for item in global_annual.values()]
            existing_ends = {item['_end_dt'] for item in filtered_entries}
            for annual_end, annual_start, annual_val, annual_fy in annual_entries:
                # FIX 2: Tighten from 45 days to 10 days.
                # 45-day window was too loose — a restated 10-K with an end date 1-15 days
                # off from the original could slip through as a "new" annual and produce
                # a second garbage Q4. 10 days catches true date-off-by-one errors only.
                already_exists = any(abs((annual_end - existing_end).days) <= 10 for existing_end in existing_ends)
                if already_exists:
                    continue
                q_in_year = [item for item in global_dedup.values() if item['_end_dt'] > annual_start and item['_end_dt'] <= annual_end]
                if len(q_in_year) == 3:
                    # FIX 3: Validate that the 3 quarters are actually Q1, Q2, Q3.
                    # Old code: any 3 quarters falling in the annual window were used,
                    # so Q1+Q2+Q4 could produce a "Q4" that was really Q3, silently wrong.
                    # New code: only proceed if the fp labels are exactly {Q1, Q2, Q3}.
                    fps_in_year = {str(item.get('_fp', '') or '').upper() for item in q_in_year}
                    if fps_in_year != {'Q1', 'Q2', 'Q3'}:
                        continue
                    q4_val = annual_val - sum(item['_val'] for item in q_in_year)
                    if not _is_implausible(q4_val, [item['_val'] for item in q_in_year]):
                        derived = {
                            '_end_dt': annual_end,
                            '_val': q4_val,
                            'form': 'edgar_derived_q4',
                            '_fy': q_in_year[0]['_fy'],
                            '_fp': 'Q4',
                        }
                        filtered_entries.append(derived)
                        existing_ends.add(annual_end)

            filtered_entries.sort(key=lambda x: x['_end_dt'], reverse=True)
            return filtered_entries

        primary_entries = []
        for concept in concepts:
            concept_entries = _extract_for_concept(concept)
            if concept_entries and concept_entries[0]['_end_dt'] < recency_cutoff:
                concept_entries = []
            
            if not primary_entries and len(concept_entries) >= 4:
                primary_entries = concept_entries
            elif primary_entries:
                existing_ends = {item['_end_dt'] for item in primary_entries}
                for entry in concept_entries:
                    already_exists = any(abs((entry['_end_dt'] - e).days) <= 60 for e in existing_ends)
                    if not already_exists:
                        primary_entries.append(entry)
                        existing_ends.add(entry['_end_dt'])
        
        primary_entries.sort(key=lambda x: x['_end_dt'], reverse=True)
        primary_entries = primary_entries[:16]
        
        if len(primary_entries) < 3:
            return [], [], [], [], [], []
        if primary_entries[0]['_end_dt'] < recency_cutoff:
            return [], [], [], [], [], []
            
        primary_entries.reverse()  # chronological ascending
        
        vals    = [item['_val'] for item in primary_entries]
        ends    = [item['_end_dt'].isoformat() for item in primary_entries]
        lbls    = [_get_fq_fy(item['_end_dt'], fy_end_month) for item in primary_entries]
        fy_list = [item.get('_fy') for item in primary_entries]
        fp_list = [item.get('_fp') for item in primary_entries]
        form_list = [item.get('form') for item in primary_entries]
        
        return vals, lbls, ends, fy_list, fp_list, form_list



    # ── FactSet-style normalized EPS: NI / split-adj diluted shares ───────────

    def _fetch_edgar_eps_normalized() -> tuple:
        """Compute normalized diluted EPS = NetIncomeLoss / split-adjusted
        WeightedAverageNumberOfDilutedSharesOutstanding.  Matches FactSet/TV."""
        facts = get_edgar_facts(ticker)
        if not facts:
            return [], [], [], [], [], []

        usgaap = facts.get('facts', {}).get('us-gaap', {})
        cutoff   = (datetime.utcnow() - timedelta(days=365 * 5)).date()
        recency  = (datetime.utcnow() - timedelta(days=548)).date()

        def _standalone_concept(concept, unit, is_annual=False):
            by_end = {}
            for e in usgaap.get(concept, {}).get('units', {}).get(unit, []):
                form = str(e.get('form', '')).upper()
                if is_annual:
                    if form not in ('10-K', '20-F'): continue
                else:
                    if form not in ('10-Q', '10-K', '20-F', '6-K'): continue
                
                end_s   = str(e.get('end',   '')).strip()
                start_s = str(e.get('start', '')).strip()
                val = _sf(e.get('val'))
                if not end_s or not start_s or val is None:
                    continue
                try:
                    end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
                    start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
                except Exception:
                    continue
                if end_dt < cutoff:
                    continue
                duration = (end_dt - start_dt).days
                if is_annual:
                    if not (335 <= duration <= 395): continue
                else:
                    if not (75 <= duration <= 105): continue
                
                entry = {
                    '_end_dt':   end_dt,
                    '_start_dt': start_dt,
                    '_val':      float(val),
                    '_fy':       int(e['fy']) if e.get('fy') is not None else end_dt.year,
                    '_fp':       str(e['fp']).strip().upper() if e.get('fp') else None,
                    'form':      form,
                }
                by_end[end_s] = entry
            return by_end

        # Split history: cumulative factor for each historical quarter =
        # product of all splits that occurred AFTER the quarter end date.
        try:
            splits_raw = yf.Ticker(ticker).splits
            splits = []
            for dt, ratio in splits_raw.items():
                d = dt.date() if hasattr(dt, 'date') else datetime.strptime(str(dt)[:10], '%Y-%m-%d').date()
                splits.append((d, float(ratio)))
            splits.sort(key=lambda x: x[0])
        except Exception:
            splits = []

        sh_map = {}
        for c in ['WeightedAverageNumberOfDilutedSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingDiluted']:
            c_map = _standalone_concept(c, 'shares', is_annual=False)
            if c_map:
                sh_map = c_map
                break
                
        sh_ann = {}
        for c in ['WeightedAverageNumberOfDilutedSharesOutstanding', 'WeightedAverageNumberOfSharesOutstandingDiluted']:
            c_map = _standalone_concept(c, 'shares', is_annual=True)
            if c_map:
                sh_ann = c_map
                break

        results = []
        ni_concepts = ['NetIncomeLoss', 'NetIncome', 'ProfitLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic']
        
        for concept in ni_concepts:
            concept_results = []
            ni_map = _standalone_concept(concept, 'USD', is_annual=False)
            ni_ann = _standalone_concept(concept, 'USD', is_annual=True)
            
            if ni_map and sh_map:
                for end_s, ni in ni_map.items():
                    end_dt = ni['_end_dt']
                    best_sh = None; best_diff = 31
                    for sh in sh_map.values():
                        d = abs((sh['_end_dt'] - end_dt).days)
                        if d < best_diff:
                            best_diff = d; best_sh = sh
                    if best_sh is None or best_sh['_val'] == 0:
                        continue
                    cum = 1.0
                    for split_dt, ratio in splits:
                        if split_dt > end_dt:
                            cum *= ratio
                    adj_shares = best_sh['_val'] * cum
                    if adj_shares == 0:
                        continue
                    concept_results.append({
                        '_end_dt':  end_dt,
                        '_val':     ni['_val'] / adj_shares,
                        '_fy':      ni['_fy'],
                        '_fp':      ni['_fp'],
                        'form':     ni['form'],
                    })

            if ni_ann and sh_ann:
                for end_s, ni_a in ni_ann.items():
                    end_dt = ni_a['_end_dt']
                    if any(abs((r['_end_dt'] - end_dt).days) <= 45 for r in concept_results):
                        continue
                        
                    best_sh = None; best_diff = 31
                    for sh_a in sh_ann.values():
                        d = abs((sh_a['_end_dt'] - end_dt).days)
                        if d < best_diff:
                            best_diff = d; best_sh = sh_a
                    if best_sh is None or best_sh['_val'] == 0: continue
                    
                    q_in_year = [q for q in ni_map.values() if q['_end_dt'] > ni_a['_start_dt'] and q['_end_dt'] <= end_dt]
                    if len(q_in_year) == 3:
                        q4_ni = ni_a['_val'] - sum(q['_val'] for q in q_in_year)
                        if not _is_implausible(q4_ni, [q['_val'] for q in q_in_year]):
                            cum = 1.0
                            for split_dt, ratio in splits:
                                if split_dt > end_dt:
                                    cum *= ratio
                            adj_shares = best_sh['_val'] * cum
                            if adj_shares == 0: continue
                            
                            concept_results.append({
                                '_end_dt':  end_dt,
                                '_val':     q4_ni / adj_shares,
                                '_fy':      ni_a['_fy'],
                                '_fp':      ni_a['_fp'] if ni_a['_fp'] else 'Q4',
                                'form':     'edgar_derived_q4',
                            })
            
            if concept_results and max(r['_end_dt'] for r in concept_results) >= recency and len(concept_results) >= 4:
                results = concept_results
                break

        if not results:
            fb_by_end = {}
            for e in usgaap.get('EarningsPerShareDiluted', {}).get('units', {}).get('USD/shares', []):
                form = str(e.get('form', '')).upper()
                if form not in ('10-Q', '6-K'):
                    continue
                end_s   = str(e.get('end',   '')).strip()
                start_s = str(e.get('start', '')).strip()
                val = _sf(e.get('val'))
                if not end_s or not start_s or val is None:
                    continue
                try:
                    end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
                    start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
                except Exception:
                    continue
                if end_dt < cutoff:
                    continue
                if not (75 <= (end_dt - start_dt).days <= 185):
                    continue
                entry = {
                    '_end_dt':   end_dt,
                    '_val':      float(val),
                    '_fy':       int(e['fy']) if e.get('fy') is not None else end_dt.year,
                    '_fp':       str(e['fp']).strip().upper() if e.get('fp') else None,
                    'form':      form,
                    '_duration': (end_dt - start_dt).days,
                }
                fb_by_end[end_s] = entry
            if not fb_by_end:
                return [], [], [], [], [], []  # foreign_filer_no_data
            results = list(fb_by_end.values())

            # Level 3: if all level-2 results are semi-annual (duration > 105d),
            # fetch true quarterly EPS from FMP first, then yfinance as sub-fallback.
            # FMP is gated behind _HAS_FMP — no hardcoded keys.
            if results and all(r.get('_duration', 0) > 105 for r in results):
                if _HAS_FMP:
                    try:
                        fr = requests.get(
                            f'https://financialmodelingprep.com/api/v3/income-statement/{ticker}',
                            params={'period': 'quarter', 'limit': 12, 'apikey': FMP_API_KEY},
                            timeout=10
                        )
                        fr.raise_for_status()
                        fmp_data = fr.json() if isinstance(fr.json(), list) else []
                        fmp_results = []
                        for item in fmp_data:
                            date_str = str(item.get('date', '')).strip()
                            eps = _sf(item.get('epsDiluted')) or _sf(item.get('eps'))
                            if not date_str or eps is None:
                                continue
                            try:
                                end_dt = datetime.strptime(date_str, '%Y-%m-%d').date()
                            except Exception:
                                continue
                            if end_dt < cutoff:
                                continue
                            fmp_results.append({
                                '_end_dt':   end_dt,
                                '_val':      float(eps),
                                '_fy':       end_dt.year,
                                '_fp':       None,
                                'form':      'FMP',
                                '_duration': 90,
                            })
                        if len(fmp_results) >= 4:
                            results = fmp_results
                    except Exception:
                        pass

            # Level 3b: FMP unavailable — try yfinance earnings_dates (Reported EPS).
            # earnings_dates has 8 quarters; apply ann_date-45d snap to get
            # proper fiscal quarter-end dates for labeling and YoY matching.
            if results and all(r.get('_duration', 0) > 105 for r in results):
                try:
                    import calendar as _cal
                    _qmonths = {((fy_end_month - 1 - off) % 12) + 1 for off in [0, 3, 6, 9]}

                    def _snap_qend_l3(dt):
                        cands = []
                        for yr in [dt.year - 1, dt.year, dt.year + 1]:
                            for m in _qmonths:
                                last = _cal.monthrange(yr, m)[1]
                                cands.append(datetime(yr, m, last).date())
                        return min(cands, key=lambda c: abs((c - dt).days))

                    ed = yf.Ticker(ticker).earnings_dates
                    if ed is not None and not ed.empty and 'Reported EPS' in ed.columns:
                        df_ed = ed[['Reported EPS']].dropna()
                        yf_results = []
                        for ts, row in df_ed.sort_index(ascending=False).head(12).iterrows():
                            try:
                                ann_dt = ts.date() if hasattr(ts, 'date') else \
                                         datetime.strptime(str(ts)[:10], '%Y-%m-%d').date()
                                fiscal_end = _snap_qend_l3(ann_dt - timedelta(days=45))
                                val = float(row['Reported EPS'])
                            except Exception:
                                continue
                            if fiscal_end < cutoff:
                                continue
                            yf_results.append({
                                '_end_dt':   fiscal_end,
                                '_val':      val,
                                '_fy':       fiscal_end.year,
                                '_fp':       None,
                                'form':      'yfinance',
                                '_duration': 90,
                            })
                        # Deduplicate by fiscal_end (keep first = most recent filing)
                        seen_ends = {}
                        for yr in sorted(yf_results, key=lambda x: x['_end_dt'], reverse=True):
                            k = yr['_end_dt'].isoformat()
                            if k not in seen_ends:
                                seen_ends[k] = yr
                        yf_results = sorted(seen_ends.values(), key=lambda x: x['_end_dt'])
                        if len(yf_results) >= 4:
                            results = yf_results
                except Exception:
                    pass  # keep level-2 semi-annual as final fallback

        results.sort(key=lambda x: x['_end_dt'], reverse=True)
        results = results[:8]
        if results and results[0]['_end_dt'] < recency:
            return [], [], [], [], [], []
        results.reverse()

        return (
            [r['_val'] for r in results],
            [_get_fq_fy(r['_end_dt'], fy_end_month) for r in results],
            [r['_end_dt'].isoformat() for r in results],
            [r['_fy']  for r in results],
            [r['_fp']  for r in results],
            [r['form'] for r in results],
        )

    # ── Fetch each metric independently ───────────────────────────────────────

    rev_keys_edgar = ['RevenueFromContractWithCustomerExcludingAssessedTax',

                      'RevenueFromContractWithCustomerIncludingAssessedTax',

                      'Revenues',

                      'SalesRevenueNet',

                      'SalesRevenueGoodsNet',

                      'RevenueFromContractWithCustomer']

    ni_keys_edgar  = ['NetIncomeLoss',

                      'NetIncome',

                      'ProfitLoss',

                      'NetIncomeLossAvailableToCommonStockholdersBasic']



    # ── Fetch from all sources ─────────────────────────────────────────────────

    (fmp_rev, fmp_rev_lbl, fmp_rev_end, fmp_rev_fy, fmp_rev_fp,

     fmp_ni,  fmp_ni_lbl,  fmp_ni_end,  fmp_ni_fy,  fmp_ni_fp,

     fmp_margin, fmp_margin_lbl, fmp_margin_end,

     fmp_eps, fmp_eps_lbl, fmp_eps_end, fmp_eps_fy, fmp_eps_fp) = _fmp_fetch_revenue_ni(ticker)



    edgar_rev, edgar_rev_lbl, edgar_rev_end, edgar_rev_fy, edgar_rev_fp, edgar_rev_form = _edgar_metric(rev_keys_edgar, is_revenue=True)



    edgar_ni_abs, edgar_ni_lbl, edgar_ni_end, edgar_ni_fy, edgar_ni_fp, edgar_ni_form = _edgar_metric(ni_keys_edgar)

    # Normalized EPS: NI / split-adjusted diluted shares (FactSet / TV method)
    edgar_eps, edgar_eps_lbl, edgar_eps_end, edgar_eps_fy, edgar_eps_fp, edgar_eps_form = _fetch_edgar_eps_normalized()



    # ── EPS: Finnhub stock/earnings (adjusted) primary ────────────────────────
    fh_eps, fh_eps_end = [], []
    if _HAS_FINNHUB:
        try:
            _fh_r = requests.get(
                'https://finnhub.io/api/v1/stock/earnings',
                params={'symbol': ticker.upper(), 'limit': 12, 'token': FINNHUB_KEY},
                timeout=8
            )
            if _fh_r.status_code == 200:
                _fh_data = _fh_r.json() if isinstance(_fh_r.json(), list) else []
                _fh_rows = []
                for _item in _fh_data:
                    _period = str(_item.get('period', '')).strip()
                    _actual = _sf(_item.get('actual'))
                    if not _period or _actual is None:
                        continue
                    try:
                        _dt = datetime.strptime(_period, '%Y-%m-%d').date()
                    except Exception:
                        continue
                    _fh_rows.append((_dt, float(_actual)))
                _fh_rows = sorted(_fh_rows, key=lambda x: x[0], reverse=True)[:12]
                _fh_rows.reverse()
                fh_eps     = [v for _, v in _fh_rows]
                fh_eps_end = [d.isoformat() for d, _ in _fh_rows]
        except Exception:
            pass



    # Concept mismatch guard: if sources differ by >5x, EDGAR has wrong concept

    if fmp_rev and edgar_rev:

        fmp_vals = [v for v in fmp_rev if v is not None]

        fmp_avg = sum(fmp_vals) / len(fmp_vals) if fmp_vals else 0

        edgar_vals = [v for v in edgar_rev if v is not None]

        edgar_avg = sum(edgar_vals) / len(edgar_vals) if edgar_vals else 0

        if edgar_avg > 0 and fmp_avg > 0:

            ratio = max(fmp_avg, edgar_avg) / min(fmp_avg, edgar_avg)

            if ratio > 5:

                edgar_rev, edgar_rev_lbl, edgar_rev_end, edgar_rev_fy, edgar_rev_fp, edgar_rev_form = [], [], [], [], [], []



    if fmp_ni and edgar_ni_abs:

        fmp_ni_vals = [v for v in fmp_ni if v is not None]

        fmp_ni_avg = sum(fmp_ni_vals) / len(fmp_ni_vals) if fmp_ni_vals else 0

        edgar_ni_vals = [v for v in edgar_ni_abs if v is not None]

        edgar_ni_avg = sum(edgar_ni_vals) / len(edgar_ni_vals) if edgar_ni_vals else 0

        if fmp_ni_avg != 0 and edgar_ni_avg != 0:

            ratio = max(abs(fmp_ni_avg), abs(edgar_ni_avg)) / max(abs(min(fmp_ni_avg, edgar_ni_avg)), 1)

            if ratio > 5:

                edgar_ni_abs, edgar_ni_lbl, edgar_ni_end, edgar_ni_fy, edgar_ni_fp, edgar_ni_form = [], [], [], [], [], []



    # ── EPS sanity filter ─────────────────────────────────────────────────────

    def _sane_eps(vals):

        return [(v if v is not None and -500 <= v <= 5000 else None) for v in vals]



    eps_fmp_clean   = _sane_eps(fmp_eps)

    eps_edgar_clean = _sane_eps(edgar_eps)



    # ── yfinance fallback fetch ───────────────────────────────────────────────

    try:

        import yfinance as _yf

        _yf_ticker = _yf.Ticker(ticker)

        yf_q = _yf_ticker.quarterly_income_stmt

        def _yf_series(keys):

            if yf_q is None or yf_q.empty:

                return [], []

            for k in keys:

                if k in yf_q.index:

                    cols = sorted(yf_q.columns, reverse=False)

                    vals = [_sf(yf_q.loc[k, c]) for c in cols]

                    ends = [c.strftime('%Y-%m-%d') for c in cols]

                    return vals, ends

            return [], []

        yf_rev, yf_rev_end = _yf_series(['Total Revenue', 'Revenue'])

        yf_ni,  yf_ni_end  = _yf_series(['Net Income', 'Net Income Common Stockholders'])

        yf_eps, yf_eps_end = _yf_series(['Diluted EPS', 'Basic EPS'])

    except Exception:

        yf_rev = yf_rev_end = yf_ni = yf_ni_end = yf_eps = yf_eps_end = []



    # ── yfinance Fallback Injection ───────────────────────────────────────────

    # If FMP failed (e.g. 402 error for un-subscribed tickers), try EDGAR first, then yfinance.
    if not fmp_rev or len(fmp_rev) < 4:
        if edgar_rev and len(edgar_rev) >= 4:
            fmp_rev, fmp_rev_lbl, fmp_rev_end, fmp_rev_fy, fmp_rev_fp = edgar_rev, edgar_rev_lbl, edgar_rev_end, edgar_rev_fy, edgar_rev_fp
        elif yf_rev:
            fmp_rev, fmp_rev_end = yf_rev, yf_rev_end
            fmp_rev_fy, fmp_rev_fp = [None] * len(yf_rev), [None] * len(yf_rev)

    if not fmp_ni or len(fmp_ni) < 4:
        if edgar_ni_abs and len(edgar_ni_abs) >= 4:
            fmp_ni, fmp_ni_lbl, fmp_ni_end, fmp_ni_fy, fmp_ni_fp = edgar_ni_abs, edgar_ni_lbl, edgar_ni_end, edgar_ni_fy, edgar_ni_fp
        elif yf_ni:
            fmp_ni, fmp_ni_end = yf_ni, yf_ni_end
            fmp_ni_fy, fmp_ni_fp = [None] * len(yf_ni), [None] * len(yf_ni)



    # ── Revenue YoY ───────────────────────────────────────────────────────────
    # Primary: utils/secfs_revenue.py (local secfsdstools parquet DB, fast).
    # Fallback: utils/edgar_revenue.py (edgartools, live HTTP, newer quarters
    # than the local bulk DB can have). Last resort: FMP/EDGAR-raw-concepts
    # pipeline when neither of the above returns enough/recent-enough data.
    secfs_rev_vals, secfs_rev_ends = [], []
    if _HAS_SECFS_REV:
        try:
            _secfs_rev = sorted(get_quarterly_revenue_secfs(ticker, n_quarters=16), key=lambda r: r['period_end'])
        except Exception:
            _secfs_rev = []
        for r in _secfs_rev:
            secfs_rev_vals.append(r['revenue_m'] * 1_000_000)  # millions -> raw USD
            secfs_rev_ends.append(r['period_end'].isoformat())

    rev_yoy_secfs, rev_labels_secfs, _, _, _ = _date_first_yoy(
        secfs_rev_vals, secfs_rev_ends, [], [], None, None, None, None,
        fy_end_m=fy_end_month, append_none=True
    )

    _use_secfs_rev = (
        len([x for x in rev_yoy_secfs if x is not None]) >= 3
        and _is_recent(secfs_rev_ends)
    )

    # Skip the live edgartools HTTP fetch entirely when secfs already gave us
    # a good-enough series — it's the slowest tier and would otherwise run on
    # every ticker for no benefit.
    edgartools_rev_vals, edgartools_rev_ends = [], []
    if _HAS_EDGARTOOLS_REV and not _use_secfs_rev:
        try:
            _et_rev = sorted(get_quarterly_revenue(ticker, n_quarters=16), key=lambda r: r['period_end'])
        except Exception:
            _et_rev = []
        for r in _et_rev:
            edgartools_rev_vals.append(r['revenue_m'] * 1_000_000)  # millions -> raw USD
            edgartools_rev_ends.append(r['period_end'].isoformat())

    rev_yoy_edgartools, rev_labels_edgartools, _, _, _ = _date_first_yoy(
        edgartools_rev_vals, edgartools_rev_ends, [], [], None, None, None, None,
        fy_end_m=fy_end_month, append_none=True
    )

    rev_yoy_existing, rev_labels_existing, _, _, _ = _date_first_yoy(fmp_rev, fmp_rev_end, edgar_rev, edgar_rev_end, fmp_rev_fy, fmp_rev_fp, None, None, fy_end_m=fy_end_month, append_none=True)

    _use_edgartools_rev = (
        not _use_secfs_rev
        and len([x for x in rev_yoy_edgartools if x is not None]) >= 3
        and _is_recent(edgartools_rev_ends)
    )

    if _use_secfs_rev:
        rev_yoy_final, rev_labels_final = rev_yoy_secfs, rev_labels_secfs
        rev_raw_final, rev_raw_ends_final = secfs_rev_vals, secfs_rev_ends
        sources['rev'] = 'secfsdstools'
    elif _use_edgartools_rev:
        rev_yoy_final, rev_labels_final = rev_yoy_edgartools, rev_labels_edgartools
        rev_raw_final, rev_raw_ends_final = edgartools_rev_vals, edgartools_rev_ends
        sources['rev'] = 'EDGAR-edgartools'
    else:
        rev_yoy_final, rev_labels_final = rev_yoy_existing, rev_labels_existing
        rev_raw_final      = edgar_rev     if edgar_rev     else fmp_rev
        rev_raw_ends_final = edgar_rev_end if edgar_rev     else fmp_rev_end
        sources['rev'] = 'FMP|EDGAR' if rev_yoy_final else 'insufficient'

    log.info("code33_engine: %s rev source = %s", ticker, sources['rev'])



    # ── Net Profit Margin pool (replaces NI YoY) ─────────────────────────────
    # Primary: utils/secfs_net_margin.py (local secfsdstools parquet DB, fast).
    # Fallback: utils/edgar_net_margin.py (edgartools, live HTTP, newer
    # quarters than the local bulk DB can have). Last resort: FMP/EDGAR-raw-
    # concepts margin pool when neither of the above returns enough/recent-
    # enough data.
    secfs_npm_vals, secfs_npm_labels, secfs_npm_ends = [], [], []
    if _HAS_SECFS_MARGIN:
        try:
            _secfs_npm = sorted(get_quarterly_net_margin_secfs(ticker, n_quarters=16), key=lambda r: r['period_end'])
        except Exception:
            _secfs_npm = []
        for r in _secfs_npm:
            secfs_npm_vals.append(r['net_margin_pct'])
            secfs_npm_ends.append(r['period_end'].isoformat())
            secfs_npm_labels.append(_get_fq_fy(r['period_end'], fy_end_month))

    _use_secfs_npm = (
        len([x for x in secfs_npm_vals if x is not None]) >= 3
        and _is_recent(secfs_npm_ends)
    )

    # Skip the live edgartools HTTP fetch entirely when secfs already gave us
    # a good-enough series — it's the slowest tier and would otherwise run on
    # every ticker for no benefit.
    edgartools_npm_vals, edgartools_npm_labels, edgartools_npm_ends = [], [], []
    if _HAS_EDGARTOOLS_MARGIN and not _use_secfs_npm:
        try:
            _et_npm = sorted(get_quarterly_net_margin(ticker, n_quarters=16), key=lambda r: r['period_end'])
        except Exception:
            _et_npm = []
        for r in _et_npm:
            edgartools_npm_vals.append(r['net_margin_pct'])
            edgartools_npm_ends.append(r['period_end'].isoformat())
            edgartools_npm_labels.append(_get_fq_fy(r['period_end'], fy_end_month))

    npm_vals_existing, npm_labels_existing, npm_ends_existing = _build_margin_pool(

        fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,

        edgar_rev, edgar_rev_end, edgar_ni_abs, edgar_ni_end, fy_end_m=fy_end_month

    )

    _use_edgartools_npm = (
        not _use_secfs_npm
        and len([x for x in edgartools_npm_vals if x is not None]) >= 3
        and _is_recent(edgartools_npm_ends)
    )

    if _use_secfs_npm:
        npm_vals, npm_labels_final, npm_ends_final = secfs_npm_vals, secfs_npm_labels, secfs_npm_ends
        sources['ni'] = 'secfsdstools'
    elif _use_edgartools_npm:
        npm_vals, npm_labels_final, npm_ends_final = edgartools_npm_vals, edgartools_npm_labels, edgartools_npm_ends
        sources['ni'] = 'EDGAR-edgartools'
    else:
        npm_vals, npm_labels_final, npm_ends_final = npm_vals_existing, npm_labels_existing, npm_ends_existing
        sources['ni'] = 'FMP|EDGAR' if npm_vals else 'insufficient'

    log.info("code33_engine: %s ni source = %s", ticker, sources['ni'])

    ni_raw_final      = edgar_ni_abs if edgar_ni_abs else fmp_ni

    ni_raw_ends_final = edgar_ni_end if edgar_ni_abs else fmp_ni_end



    # ── EPS merge: Finnhub (adjusted) primary, EDGAR fills gaps ──────────────
    # Finnhub wins for any quarter where its date is within 45 days of an
    # EDGAR entry. 45d handles fiscal-calendar companies like NVDA where
    # Finnhub uses Sep-30 and EDGAR uses Oct-26 for the same quarter.
    # EDGAR-only quarters preserve fy/fp for fiscal-period YoY matching.

    eps_fh_clean = _sane_eps(fh_eps)

    _eps_pool = []
    for _v, _e in zip(eps_fh_clean, fh_eps_end):
        if _v is None or not _e:
            continue
        try:
            _dt = datetime.strptime(_e, '%Y-%m-%d').date()
            _eps_pool.append({'dt': _dt, 'val': _v, 'src': 'finnhub', 'fy': None, 'fp': None})
        except Exception:
            pass

    for _i, (_v, _e) in enumerate(zip(eps_edgar_clean, edgar_eps_end)):
        if _v is None or not _e:
            continue
        try:
            _dt = datetime.strptime(_e, '%Y-%m-%d').date()
        except Exception:
            continue
        if any(abs((_dt - _p['dt']).days) <= 45 for _p in _eps_pool):
            continue
        _fy = edgar_eps_fy[_i] if _i < len(edgar_eps_fy) else None
        _fp = edgar_eps_fp[_i] if _i < len(edgar_eps_fp) else None
        _eps_pool.append({'dt': _dt, 'val': _v, 'src': 'edgar', 'fy': _fy, 'fp': _fp})

    _eps_pool.sort(key=lambda x: x['dt'])

    _merged_eps_vals = [_p['val'] for _p in _eps_pool]
    _merged_eps_ends = [_p['dt'].isoformat() for _p in _eps_pool]
    _merged_eps_fy   = [_p['fy'] for _p in _eps_pool]
    _merged_eps_fp   = [_p['fp'] for _p in _eps_pool]

    # -- EPS YoY: N/A guards applied after pairing:
    #   - abs(prior) < 0.10 -> keep as None (denominator instability)
    #   - abs(rate) > 999%  -> keep as None (extreme / meaningless)
    #   - sign flip         -> keep but append [NM] to label

    eps_yoy_raw, eps_labels_raw, eps_yoy_ends_raw, eps_prior_vals_raw, eps_sources_raw = _date_first_yoy(
        _merged_eps_vals, _merged_eps_ends, [], [], _merged_eps_fy, _merged_eps_fp, None, None,
        fy_end_m=fy_end_month, src_primary='finnhub', src_fallback='edgar'
    )

    eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals, eps_sources = [], [], [], [], []
    for rate, label, end, prior, src in zip(
            eps_yoy_raw, eps_labels_raw, eps_yoy_ends_raw, eps_prior_vals_raw, eps_sources_raw):
        # Always keep quarter in pool — mark rate as None instead of skipping.
        # Skipping reduces raw quarter count below 8 -> false INSUFFICIENT.
        if prior is None or abs(prior) < 0.10 or abs(rate) > 999:
            eps_yoy_final.append(None)
            eps_labels_final.append(label)
            eps_yoy_ends.append(end)
            eps_prior_vals.append(prior)
            eps_sources.append(src)
            continue
        # Sign flip: prior > 0 and went negative, or prior < 0 and went positive
        sign_flip = (prior > 0 and rate < -100) or (prior < 0 and rate > 100)
        eps_yoy_final.append(rate)
        eps_labels_final.append(f'{label} [NM]' if sign_flip else label)
        eps_yoy_ends.append(end)
        eps_prior_vals.append(prior)
        eps_sources.append(src)

    eps_raw_final      = _merged_eps_vals
    eps_raw_ends_final = _merged_eps_ends

    sources['eps'] = 'Finnhub|EDGAR' if eps_yoy_final else 'insufficient'



    # -- Recency check (BUG 3 FIX) -----------------------------------------

    # Use max end date across ALL rev sources (FMP + EDGAR), not EDGAR-only.

    # Old code used edgar_rev_end -> false INSUFFICIENT when FMP has data

    # but EDGAR lags (e.g. small caps not well covered by EDGAR XBRL).

    all_rev_ends_combined = [e for e in (fmp_rev_end or []) + (edgar_rev_end or []) + (edgartools_rev_ends or []) if e]

    if not _is_recent(all_rev_ends_combined):

        rev_yoy_final, rev_labels_final = [], []

        rev_raw_final, rev_raw_ends_final = [], []

        sources['rev'] = 'insufficient'



    status, _d1, _d2 = _c33_status(rev_yoy_final or [], npm_vals or [])

    return {

        # Raw values aligned with raw end dates (for test + debug count)

        'eps': eps_raw_final, 'rev': rev_raw_final, 'ni': ni_raw_final,

        'eps_end_dates': eps_raw_ends_final,

        'rev_end_dates': rev_raw_ends_final,

        'ni_end_dates':  ni_raw_ends_final,

        # Pre-computed per-pair YoY (for render site — never mixes sources)

        'eps_yoy': eps_yoy_final, 'rev_yoy': rev_yoy_final,

        'eps_labels': eps_labels_final, 'rev_labels': rev_labels_final,

        # Net profit margin series (sequential, not YoY)

        'npm': npm_vals, 'npm_labels': npm_labels_final, 'npm_ends': npm_ends_final,

        'sources': sources, 'is_us': is_us,

        'sector_excluded': sector_excluded, 'excluded_sector_name': excluded_sector_name,

        'is_reit': is_reit,

        'status': status,

        'eps_prior_vals': eps_prior_vals if eps_yoy_final else [],

        'eps_sources': eps_sources if eps_yoy_final else [],

    }

def _c33_status(rev_rates: list, npm_vals: list = None) -> tuple:
    """(status, d1, d2) — green/yellow/red/insufficient.

    Code 33 (2026-06-24: EPS removed from the signal — Revenue + Net Margin
    only) requires BOTH simultaneously for 3 consecutive quarters:
      - Revenue YoY growth RATE accelerating (delta > 0)
      - Net Profit Margin expanding (delta > 0)

    Status rules:
      GREEN  = both metrics have positive deltas, accelerating (d2 >= d1)
      YELLOW = both deltas positive but acceleration shrinking (d2 < d1)
      RED    = revenue rate negative, OR any delta negative (deceleration)
    """
    def _last3(arr):
        if not arr: return None
        clean = [x for x in arr if x is not None]
        return clean[-3:] if len(clean) >= 3 else None

    rev3 = _last3(rev_rates)
    npm3 = _last3(npm_vals) if npm_vals else None

    # Need both metrics for Code 33
    if rev3 is None or npm3 is None:
        return 'insufficient', None, None

    # Rev rates must all be positive (negative = declining)
    if any(r < 0 for r in rev3):
        return 'red', None, None

    # Compute deltas for both metrics
    all_d = []
    for m in [rev3, npm3]:
        all_d.append((m[1] - m[0], m[2] - m[1]))

    rev_d1, rev_d2 = all_d[0]

    # RED: any delta negative in any metric (deceleration)
    if any(d1 < 0 or d2 < 0 for d1, d2 in all_d):
        return 'red', rev_d1, rev_d2

    # GREEN: all deltas positive AND acceleration increasing (d2 >= d1)
    if all(d2 >= d1 for d1, d2 in all_d):
        return 'green', rev_d1, rev_d2

    # YELLOW: all deltas positive but at least one metric's acceleration slowing
    return 'yellow', rev_d1, rev_d2