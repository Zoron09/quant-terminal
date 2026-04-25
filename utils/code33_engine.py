import os
import sys
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import streamlit as st
from dotenv import load_dotenv

# Load env vars from root .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from utils.sec_edgar import get_cik

# ── API keys ──────────────────────────────────────────────────────────────────
FMP_API_KEY = os.getenv('FMP_API_KEY', '')
_HAS_FMP    = bool(FMP_API_KEY)

try:
    from utils.finnhub_client import FINNHUB_KEY
    _HAS_FINNHUB = bool(FINNHUB_KEY)
except Exception:
    FINNHUB_KEY  = ''
    _HAS_FINNHUB = False

CACHE_VERSION = 'v2'

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

                if abs((d1 - d2).days) <= 45:

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



        # ── Source lock: FMP rev + FMP ni (same source, within 45 days) ──────

        fmp_rev_val = None

        fmp_ni_val  = None

        for fd in fmp_rev_map:

            try:

                if abs((d_dt - datetime.strptime(fd, '%Y-%m-%d').date()).days) <= 45:

                    fmp_rev_val = fmp_rev_map[fd]

                    break

            except Exception:

                pass

        if fmp_rev_val is not None:

            for fd in fmp_ni_map:

                try:

                    if abs((d_dt - datetime.strptime(fd, '%Y-%m-%d').date()).days) <= 45:

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

                    if abs((d_dt - datetime.strptime(ed, '%Y-%m-%d').date()).days) <= 45:

                        edgar_rev_val = edgar_rev_map[ed]

                        break

                except Exception:

                    pass

            if edgar_rev_val is not None:

                for ed in edgar_ni_map:

                    try:

                        if abs((d_dt - datetime.strptime(ed, '%Y-%m-%d').date()).days) <= 45:

                            edgar_ni_val = edgar_ni_map[ed]

                            break

                    except Exception:

                        pass

            if edgar_rev_val is not None and edgar_ni_val is not None and edgar_rev_val > 0:

                margin = (edgar_ni_val / edgar_rev_val) * 100



        if margin is not None:

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

def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends, fmp_fy=None, fmp_fp=None, edgar_fy=None, edgar_fp=None, fy_end_m=12):
    """Calculate YoY growth using strict fiscal-period matching first, fallback to date matching.
    Prevents source-mixing and historical data deletion bugs."""
    def _yoy_for_src(vals, ends, fys, fps, src_name):
        pool = []
        for v, e, fy, fp in zip(vals or [], ends or [], fys or [None]*len(vals or []), fps or [None]*len(vals or [])):
            if v is not None and e:
                pool.append({'val': float(v), 'end': e, 'fy': fy, 'fp': str(fp).strip().upper() if fp else None})
        pool.sort(key=lambda x: x['end'], reverse=True)
        deduped = []
        for entry in pool:
            duplicate = False
            for kept in deduped:
                try:
                    d1 = datetime.strptime(entry['end'], '%Y-%m-%d').date()
                    d2 = datetime.strptime(kept['end'],  '%Y-%m-%d').date()
                    if abs((d1 - d2).days) <= 45:
                        duplicate = True
                        break
                except Exception:
                    pass
            if not duplicate:
                deduped.append(entry)
        
        results = []

        seen = set()
        for i, curr in enumerate(deduped):
            if curr['end'] in seen: continue
            try:
                curr_dt = datetime.strptime(curr['end'], '%Y-%m-%d').date()
            except Exception:
                continue
            
            prior = None
            
            # 1. Strict Fiscal Period matching (Q4 -> Q4 of previous year)
            if curr['fy'] is not None and curr['fp'] in ('Q1', 'Q2', 'Q3', 'Q4'):
                target_fy = curr['fy'] - 1
                for cand in deduped:
                    if cand['end'] == curr['end']: continue
                    if cand['fy'] == target_fy and cand['fp'] == curr['fp']:
                        prior = cand
                        break
            
            # 2. Fallback to Date matching (+- 31 days from 365 days ago)
            if prior is None:
                try:
                    target_dt = curr_dt.replace(year=curr_dt.year - 1)
                except ValueError:
                    target_dt = curr_dt - timedelta(days=365)
                best_diff = 32
                for cand in deduped:
                    if cand['end'] == curr['end']: continue
                    try:
                        cand_dt = datetime.strptime(cand['end'], '%Y-%m-%d').date()
                        diff = abs((cand_dt - target_dt).days)
                        if diff < best_diff:
                            best_diff = diff
                            prior = cand
                    except Exception:
                        pass
            
            # 3. Fallback to Sequential matching (+4 quarters)
            if prior is None:
                if i + 4 < len(deduped):
                    seq_prior = deduped[i + 4]
                    try:
                        sq_dt = datetime.strptime(seq_prior['end'], '%Y-%m-%d').date()
                        diff_months = (curr_dt - sq_dt).days / 30.4
                        if 9 <= diff_months <= 15:
                            prior = seq_prior
                    except Exception:
                        pass
                        
            if prior is None or prior['val'] == 0:
                continue
                
            seen.add(curr['end'])
            rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100
            try:
                label = _get_fq_fy(curr_dt, fy_end_m)
            except Exception:
                label = curr['end']
            results.append({
                'dt': curr_dt, 'end': curr['end'], 'rate': rate, 
                'label': label, 'prior_val': prior['val'], 'curr_val': curr['val']
            })
        return results

    f_yoy = _yoy_for_src(fmp_vals, fmp_ends, fmp_fy, fmp_fp, 'FMP')
    e_yoy = _yoy_for_src(edgar_vals, edgar_ends, edgar_fy, edgar_fp, 'EDGAR')
    merged = list(f_yoy)
    for ey in e_yoy:
        duplicate_idx = -1
        for idx, fy in enumerate(merged):
            if abs((ey['dt'] - fy['dt']).days) <= 45:
                duplicate_idx = idx
                break
        if duplicate_idx == -1:
            merged.append(ey)
        else:
            # Duplicate found. Check for >5% conflict in base or current value.
            # If secondary source (EDGAR/FMP fallback) conflicts with primary by >5%, the fallback (which is structurally closer to SEC ground truth) takes precedence.
            fy = merged[duplicate_idx]
            curr_diff = abs(ey['curr_val'] - fy['curr_val']) / max(abs(ey['curr_val']), abs(fy['curr_val']), 1e-9)
            prior_diff = abs(ey['prior_val'] - fy['prior_val']) / max(abs(ey['prior_val']), abs(fy['prior_val']), 1e-9)
            if curr_diff > 0.01 or prior_diff > 0.01:
                merged[duplicate_idx] = ey
    merged.sort(key=lambda x: x['dt'])
    if len(merged) > 8:
        merged = merged[-8:]
    if merged:
        return (
            [x['rate'] for x in merged],
            [x['label'] for x in merged],
            [x['end'] for x in merged],
            [x['prior_val'] for x in merged]
        )
    return [], [], [], []

@st.cache_data(ttl=86400, show_spinner=False)

def get_code33_data(ticker: str, cache_v: str = CACHE_VERSION) -> dict:

    """Fetch EPS, Revenue, Net Margin independently for Code 33 analysis.

    EPS: Finnhub quarterly series primary, EDGAR fallback.

    Revenue + Net Margin: FMP quarterly income statement primary, EDGAR fallback.

    Need minimum 7 raw quarters per metric to compute 3 YoY rates."""

    import yfinance as yf



    # ── Pre-check currency (non-USD => NOT APPLICABLE downstream) ─────────────

    is_us = True

    sector_excluded = False

    excluded_sector_name = ''

    try:

        info = yf.Ticker(ticker.upper()).info or {}

        fy_end_month = 12
        if 'lastFiscalYearEnd' in info:
            try:
                from datetime import datetime, timezone
                fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
                fy_end_month = fy_end_dt.month
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



    # ── Finnhub helpers ────────────────────────────────────────────────────────

    def _finnhub_quarterly_series(series_list) -> tuple[list, list, list]:

        """Return (values, labels, end_dates) oldest->newest, capped 8 most recent."""

        if not isinstance(series_list, list):

            return [], [], []

        rows = []

        for item in series_list:

            if not isinstance(item, dict):

                continue

            period = str(item.get('period', '')).strip()

            val = _sf(item.get('v'))

            if not period or val is None:

                continue

            try:

                dt = datetime.strptime(period, '%Y-%m-%d').date()

            except Exception:

                continue

            rows.append((dt, float(val)))

        if not rows:

            return [], [], []

        rows = sorted(rows, key=lambda x: x[0], reverse=True)[:8]

        rows.reverse()

        vals = [v for _, v in rows]

        ends = [d.isoformat() for d, _ in rows]

        lbls = [_get_fq_fy(d, fy_end_month) for d, _ in rows]

        return vals, lbls, ends



    def _finnhub_fetch_eps(symbol: str):

        """Fetch EPS from Finnhub /stock/metric quarterly series.

        Returns (eps_vals, eps_lbls, eps_ends)."""

        if not FINNHUB_KEY:

            return [], [], []

        try:

            r = requests.get(

                "https://finnhub.io/api/v1/stock/metric",

                params={'symbol': symbol.upper(), 'metric': 'all', 'token': FINNHUB_KEY},

                timeout=10

            )

            r.raise_for_status()

            data = r.json() if isinstance(r.json(), dict) else {}

            quarterly = ((data.get('series') or {}).get('quarterly') or {})

            return _finnhub_quarterly_series(quarterly.get('eps'))

        except Exception:

            return [], [], []



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

        Two entries are same quarter if end_dates within 45 days.

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

        # Sort by date descending, then deduplicate by 45-day proximity

        pool.sort(key=lambda x: x['dt'], reverse=True)

        deduped = []

        for entry in pool:

            duplicate = False

            for kept in deduped:

                if abs((entry['dt'] - kept['dt']).days) <= 45:

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



    # ── EDGAR fetcher (independent per metric) ────────────────────────────────

    def _edgar_metric(concepts, unit='USD'):

        """Return (values, labels, end_dates, fy_list, fp_list) from SEC EDGAR filings using strict quarterly filters."""

        facts = get_edgar_facts(ticker)

        if not facts:

            return [], [], [], [], []



        usgaap = facts.get('facts', {}).get('us-gaap', {})

        cutoff_date = (datetime.utcnow() - timedelta(days=365 * 5)).date()

        recency_cutoff = (datetime.utcnow() - timedelta(days=548)).date()  # ~18 months



        global_dedup = {}

        global_ytd_6m = {}

        global_ytd_9m = {}

        global_annual = {}



        # ── Accumulate entries across ALL concepts into a unified global pool ──

        # This prevents the "first passing concept" early-return from missing

        # historical data that lives under a different XBRL tag (e.g. SalesRevenueNet

        # for older years vs RevenueFromContractWithCustomer for recent years).

        for concept in concepts:

            entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])

            if not entries:

                continue

            for e in entries:

                form = str(e.get('form', '')).strip().upper()

                if form not in ('10-Q', '10-K', '20-F', '6-K'):

                    continue

                end_str = str(e.get('end', '')).strip()

                start_str = str(e.get('start', '')).strip()

                filed_str = str(e.get('filed', '')).strip()

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

                try:

                    filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date() if filed_str else None

                except Exception:

                    filed_dt = None

                duration_days = (end_dt - start_dt).days

                end_key = e['end']

                cloned = dict(e)

                cloned['_end_dt'] = end_dt

                cloned['_filed_dt'] = filed_dt

                cloned['_val'] = float(val)

                cloned['_fy'] = int(e['fy']) if e.get('fy') is not None else end_dt.year

                cloned['_fp'] = str(e['fp']).strip().upper() if e.get('fp') else None

                cloned['form'] = form

                if 80 <= duration_days <= 105:

                    if end_key not in global_dedup:

                        global_dedup[end_key] = cloned

                    elif filed_dt and global_dedup[end_key]['_filed_dt'] and filed_dt > global_dedup[end_key]['_filed_dt']:

                        global_dedup[end_key] = cloned

                elif 170 <= duration_days <= 195:

                    if end_key not in global_ytd_6m:

                        global_ytd_6m[end_key] = cloned

                    elif filed_dt and global_ytd_6m[end_key]['_filed_dt'] and filed_dt > global_ytd_6m[end_key]['_filed_dt']:

                        global_ytd_6m[end_key] = cloned

                elif 260 <= duration_days <= 285:

                    if end_key not in global_ytd_9m:

                        global_ytd_9m[end_key] = cloned

                    elif filed_dt and global_ytd_9m[end_key]['_filed_dt'] and filed_dt > global_ytd_9m[end_key]['_filed_dt']:

                        global_ytd_9m[end_key] = cloned

                elif 350 <= duration_days <= 380:

                    if form in ('10-K', '20-F'):

                        annual_fy = int(e['fy']) if e.get('fy') is not None else None

                        f_dt = filed_dt if filed_dt else datetime.min.date()

                        if end_dt not in global_annual or f_dt > global_annual[end_dt][4]:

                            global_annual[end_dt] = (end_dt, start_dt, float(val), annual_fy, f_dt)

        # ── Post-loop: derive Q2/Q3, apply filters, derive Q4 ────────────────

        # Derive missing Q2 from YTD 6-month

        for ytd_end, ytd_entry in global_ytd_6m.items():

            if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):

                target_q1_end = ytd_entry['_end_dt'] - timedelta(days=90)

                q1_entry = next((v for v in global_dedup.values() if abs((v['_end_dt'] - target_q1_end).days) <= 25), None)

                if q1_entry:

                    derived_q2 = dict(ytd_entry)

                    derived_q2['_val'] = ytd_entry['_val'] - q1_entry['_val']

                    derived_q2['form'] = '10-Q-derived'

                    global_dedup[ytd_end] = derived_q2

        # Derive missing Q3 from YTD 9-month

        for ytd_end, ytd_entry in global_ytd_9m.items():

            if not any(abs((v['_end_dt'] - ytd_entry['_end_dt']).days) <= 15 for v in global_dedup.values()):

                target_q2_end = ytd_entry['_end_dt'] - timedelta(days=90)

                ytd_6m_entry = next((v for v in global_ytd_6m.values() if abs((v['_end_dt'] - target_q2_end).days) <= 25), None)

                if ytd_6m_entry:

                    derived_q3 = dict(ytd_entry)

                    derived_q3['_val'] = ytd_entry['_val'] - ytd_6m_entry['_val']

                    derived_q3['form'] = '10-Q-derived'

                    global_dedup[ytd_end] = derived_q3

        filtered_entries = sorted(global_dedup.values(), key=lambda x: x['_end_dt'], reverse=True)

        filtered_entries = filtered_entries[:8]

        if len(filtered_entries) < 3:

            return [], [], [], [], []

        if filtered_entries[0]['_end_dt'] < recency_cutoff:

            return [], [], [], [], []

        filtered_entries.reverse()  # chronological ascending

        # Derive missing Q4s from annual filings

        annual_entries = [(item[0], item[1], item[2], item[3]) for item in global_annual.values()]

        existing_ends = {item['_end_dt'] for item in filtered_entries}

        for annual_end, annual_start, annual_val, annual_fy in annual_entries:

            already_exists = any(abs((annual_end - existing_end).days) <= 45 for existing_end in existing_ends)

            if already_exists:

                continue

            q_in_year = [item for item in global_dedup.values() if item['_end_dt'] > annual_start and item['_end_dt'] <= annual_end]

            if len(q_in_year) == 3:

                q4_val = annual_val - sum(item['_val'] for item in q_in_year)

                derived = {

                    '_end_dt': annual_end,

                    '_filed_dt': None,

                    '_val': q4_val,

                    'form': '10-K-derived',

                    '_fy': q_in_year[0]['_fy'],

                    '_fp': 'Q4',

                }

                filtered_entries.append(derived)

                existing_ends.add(annual_end)

        filtered_entries.sort(key=lambda x: x['_end_dt'])

        vals    = [item['_val'] for item in filtered_entries]

        ends    = [item['_end_dt'].isoformat() for item in filtered_entries]

        lbls    = [_get_fq_fy(item['_end_dt'], fy_end_month) for item in filtered_entries]

        fy_list = [item.get('_fy') for item in filtered_entries]

        fp_list = [item.get('_fp') for item in filtered_entries]

        return vals, lbls, ends, fy_list, fp_list

        return [], [], [], [], []



    # ── Fetch each metric independently ───────────────────────────────────────

    eps_keys_edgar = ['EarningsPerShareDiluted', 'EarningsPerShareBasic']

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



    edgar_rev, edgar_rev_lbl, edgar_rev_end, edgar_rev_fy, edgar_rev_fp = _edgar_metric(rev_keys_edgar)



    edgar_ni_abs, edgar_ni_lbl, edgar_ni_end, edgar_ni_fy, edgar_ni_fp = _edgar_metric(ni_keys_edgar)

    edgar_eps, edgar_eps_lbl, edgar_eps_end, edgar_eps_fy, edgar_eps_fp = _edgar_metric(

        eps_keys_edgar, unit='USD/shares'

    )



    fh_eps, fh_eps_lbl, fh_eps_end = _finnhub_fetch_eps(ticker)



    # Concept mismatch guard: if sources differ by >5x, EDGAR has wrong concept

    if fmp_rev and edgar_rev:

        fmp_avg = sum(fmp_rev) / len(fmp_rev)

        edgar_vals = [v for v in edgar_rev if v is not None]

        edgar_avg = sum(edgar_vals) / len(edgar_vals) if edgar_vals else 0

        if edgar_avg > 0 and fmp_avg > 0:

            ratio = max(fmp_avg, edgar_avg) / min(fmp_avg, edgar_avg)

            if ratio > 5:

                edgar_rev, edgar_rev_lbl, edgar_rev_end, edgar_rev_fy, edgar_rev_fp = [], [], [], [], []



    if fmp_ni and edgar_ni_abs:

        fmp_ni_avg = sum(fmp_ni) / len(fmp_ni)

        edgar_ni_vals = [v for v in edgar_ni_abs if v is not None]

        edgar_ni_avg = sum(edgar_ni_vals) / len(edgar_ni_vals) if edgar_ni_vals else 0

        if fmp_ni_avg != 0 and edgar_ni_avg != 0:

            ratio = max(abs(fmp_ni_avg), abs(edgar_ni_avg)) / max(abs(min(fmp_ni_avg, edgar_ni_avg)), 1)

            if ratio > 5:

                edgar_ni_abs, edgar_ni_lbl, edgar_ni_end, edgar_ni_fy, edgar_ni_fp = [], [], [], [], []



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

    # If FMP failed (e.g. 402 error for un-subscribed tickers), inject yfinance.

    if not fmp_rev and yf_rev:

        fmp_rev, fmp_rev_end = yf_rev, yf_rev_end

        fmp_rev_fy, fmp_rev_fp = [None] * len(yf_rev), [None] * len(yf_rev)

    if not fmp_ni and yf_ni:

        fmp_ni, fmp_ni_end = yf_ni, yf_ni_end

        fmp_ni_fy, fmp_ni_fp = [None] * len(yf_ni), [None] * len(yf_ni)



    # ── Revenue YoY ───────────────────────────────────────────────────────────

    rev_yoy_final, rev_labels_final, _, _rev_prior_vals = _date_first_yoy(fmp_rev, fmp_rev_end, edgar_rev, edgar_rev_end, fmp_rev_fy, fmp_rev_fp, None, None, fy_end_m=fy_end_month)

    rev_raw_final      = edgar_rev     if edgar_rev     else fmp_rev

    rev_raw_ends_final = edgar_rev_end if edgar_rev     else fmp_rev_end

    sources['rev'] = 'FMP|EDGAR' if rev_yoy_final else 'insufficient'



    # ── Net Profit Margin pool (replaces NI YoY) ─────────────────────────────

    npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(

        fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,

        edgar_rev, edgar_rev_end, edgar_ni_abs, edgar_ni_end, fy_end_m=fy_end_month

    )

    ni_raw_final      = edgar_ni_abs if edgar_ni_abs else fmp_ni

    ni_raw_ends_final = edgar_ni_end if edgar_ni_abs else fmp_ni_end

    sources['ni'] = 'FMP|EDGAR' if npm_vals else 'insufficient'



    # -- EPS YoY (BUG 2 FIX: Finnhub=primary adjusted, FMP=secondary, EDGAR=fallback)

    # _date_first_yoy enforces strict source lock: same-source YoY pairs only.

    eps_fh_clean = _sane_eps(fh_eps)



    # Pass 1: Finnhub vs EDGAR — EDGAR has most-recently-filed (restated) values.
    # When Finnhub returns stale pre-restatement adjusted EPS, the 5% override
    # inside _date_first_yoy will substitute the EDGAR restated value.

    eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals = _date_first_yoy(
        eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end, None, None, None, None, fy_end_m=fy_end_month
    )

    # Pass 2: if < 3 YoY points, also attempt Finnhub vs FMP

    if len(eps_yoy_final) < 3:

        eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(
            eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end, None, None, fmp_eps_fy, fmp_eps_fp, fy_end_m=fy_end_month
        )

        if len(eps_yoy_e2) > len(eps_yoy_final):

            eps_yoy_final    = eps_yoy_e2

            eps_labels_final = eps_labels_e2

            eps_yoy_ends     = eps_ends_e2

            eps_prior_vals   = eps_prior_e2



    # Raw EPS for pre-profit check: prefer Finnhub > FMP > EDGAR

    if eps_fh_clean:

        eps_raw_final      = eps_fh_clean

        eps_raw_ends_final = fh_eps_end

    elif eps_fmp_clean:

        eps_raw_final      = eps_fmp_clean

        eps_raw_ends_final = fmp_eps_end

    else:

        eps_raw_final      = eps_edgar_clean

        eps_raw_ends_final = edgar_eps_end

    sources['eps'] = 'Finnhub|FMP|EDGAR' if eps_yoy_final else 'insufficient'



    # -- Recency check (BUG 3 FIX) -----------------------------------------

    # Use max end date across ALL rev sources (FMP + EDGAR), not EDGAR-only.

    # Old code used edgar_rev_end -> false INSUFFICIENT when FMP has data

    # but EDGAR lags (e.g. small caps not well covered by EDGAR XBRL).

    all_rev_ends_combined = [e for e in (fmp_rev_end or []) + (edgar_rev_end or []) if e]

    if not _is_recent(all_rev_ends_combined):

        rev_yoy_final, rev_labels_final = [], []

        rev_raw_final, rev_raw_ends_final = [], []

        sources['rev'] = 'insufficient'



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

        'eps_prior_vals': eps_prior_vals if eps_yoy_final else [],

    }

def _c33_status(rates3: list) -> tuple:

    """(status, d1, d2) — green/yellow/red/insufficient."""

    if len(rates3) < 3: return 'insufficient', None, None

    g1, g2, g3 = rates3[-3], rates3[-2], rates3[-1]

    # Any negative rate = broken immediately (pre-profit or declining)

    if g1 < 0 or g2 < 0 or g3 < 0: return 'red', None, None

    d1, d2 = g2 - g1, g3 - g2

    if d1 < 0 or d2 < 0: return 'red', d1, d2

    if d2 >= d1:          return 'green', d1, d2

    return 'yellow', d1, d2