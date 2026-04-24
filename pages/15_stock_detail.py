"""

pages/15_stock_detail.py

Stock Detail — header, OHLC, price chart, 5 tabs.

Per CLAUDE.md Section 7. SEC EDGAR primary, yfinance fallback.

Column order: oldest LEFT, newest RIGHT throughout.

"""

import streamlit as st

import sys, os

import pandas as pd

import numpy as np

import plotly.graph_objects as go

import requests

from datetime import datetime, timedelta



sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



from utils.sidebar import render_sidebar

from utils.data_fetcher import get_ticker_info, get_financials, get_price_history

from utils.alpaca_client import get_bars, get_snapshots, _HAS_ALPACA

from utils.sec_edgar import get_cik

from utils.formatters import (

    fmt_number, fmt_large_number, fmt_pct, fmt_price,

    fmt_volume, fmt_fin, fmt_date, safe_get,

)



try:

    from utils.alpaca_client import ALPACA_KEY, ALPACA_SECRET

except Exception:

    ALPACA_KEY = ALPACA_SECRET = ''



try:

    from utils.finnhub_client import fh_earnings_surprises, fh_basic_financials, FINNHUB_KEY

    _HAS_FINNHUB = bool(FINNHUB_KEY)

except Exception:

    _HAS_FINNHUB = False

    FINNHUB_KEY = ''

    def fh_earnings_surprises(x): return None

    def fh_basic_financials(x): return None



from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

FMP_API_KEY = os.getenv('FMP_API_KEY', '')

_HAS_FMP = bool(FMP_API_KEY)



# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Stock Detail · Quant Terminal", page_icon="📋", layout="wide")



_css = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', 'custom.css')

if os.path.exists(_css):

    with open(_css) as _f:

        st.markdown(f'<style>{_f.read()}</style>', unsafe_allow_html=True)



DARK   = '#0E1117'

BG     = '#161B22'

GREEN  = '#00FF41'

RED    = '#FF4444'

YELLOW = '#FFD700'

GRAY   = '#888888'

EDGAR_UA = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}



# ── Small utilities ───────────────────────────────────────────────────────────



def _nan(v):

    if v is None: return True

    try: return isinstance(v, float) and np.isnan(v)

    except Exception: return False



def _sf(v, default=None):

    if _nan(v): return default

    try: return float(v)

    except Exception: return default



def _time_ago(ts) -> str:

    try:

        if isinstance(ts, (int, float)):

            dt = datetime.utcfromtimestamp(ts)

        elif isinstance(ts, str):

            dt = datetime.fromisoformat(ts.replace('Z', ''))

        else:

            dt = ts

        diff = datetime.utcnow() - dt

        if diff.days >= 1: return f"{diff.days}d ago"

        h = diff.seconds // 3600

        if h >= 1: return f"{h}h ago"

        return f"{diff.seconds // 60}m ago"

    except Exception:

        return ''



def _fmt_cell(val, is_pct=False, already_pct=False):

    if _nan(val): return '<span style="color:#555">—</span>'

    try:

        v = float(val)

        if is_pct:

            txt = f"{v:.1f}%" if already_pct else f"{v*100:.1f}%"

            c   = GREEN if v > 0 else (RED if v < 0 else '#FFFFFF')

            return f'<span style="color:{c}">{txt}</span>'

        neg = v < 0; av = abs(v)

        if   av >= 1e12: s = f"{av/1e12:.2f}T"

        elif av >= 1e9:  s = f"{av/1e9:.2f}B"

        elif av >= 1e6:  s = f"{av/1e6:.1f}M"

        elif av >= 1e3:  s = f"{av/1e3:.1f}K"

        else:            s = f"{av:.2f}"

        return f'<span style="color:{RED}">({s})</span>' if neg else s

    except Exception:

        return '<span style="color:#555">—</span>'



def _growth_cell(curr, prev):

    """Compute % change curr vs prev. Show — if either missing or prev==0."""

    if _nan(curr) or _nan(prev) or prev == 0: return '<span style="color:#555">—</span>'

    try:

        g = (float(curr) - float(prev)) / abs(float(prev)) * 100

        c = GREEN if g >= 0 else RED

        return f'<span style="color:{c};font-size:11px;">{"+" if g>=0 else ""}{g:.1f}%</span>'

    except Exception:

        return '<span style="color:#555">—</span>'



def _pct_cell(num, denom):

    """Compute num/denom*100 and format as colored %."""

    n, d = _sf(num), _sf(denom)

    if n is None or d is None or d == 0: return '<span style="color:#555">—</span>'

    v = n / d * 100

    c = GREEN if v > 0 else (RED if v < 0 else '#FFFFFF')

    return f'<span style="color:{c}">{v:.1f}%</span>'



# ── SEC EDGAR ─────────────────────────────────────────────────────────────────



@st.cache_data(ttl=3600, show_spinner=False)

def get_edgar_facts(ticker: str) -> dict | None:

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

        # Filter by form type — consistent across all companies (no frame label dependency)

        # Balance sheet quarterly uses 10-Q same as income statement

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

            recent_8 = sorted_items[-8:]   # cap at 8 most recent to avoid 2008-era data

            return {end: float(v['val']) for end, v in recent_8}

    return {}



# ── Code 33 data fetcher — FMP + Finnhub primary, EDGAR fallback ──────────────



def _build_margin_pool(fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,

                       edgar_rev, edgar_rev_end, edgar_ni, edgar_ni_end):

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

                label = f"Q{(d_dt.month + 2) // 3} {d_dt.year}"

            except Exception:

                label = d

            margin_labels.append(label)



    # Return in chronological order (oldest first)

    margins.reverse(); margin_ends.reverse(); margin_labels.reverse()

    return margins, margin_labels, margin_ends





def _date_first_yoy(fmp_vals, fmp_ends, edgar_vals, edgar_ends):

    """Merge FMP + EDGAR pools by date, deduplicate within 45 days (FMP wins

    for most-recent; EDGAR preferred for historical), then compute YoY using

    strict date-match: for each entry find the same-source entry whose end

    date is within ±31 days of exactly 365 days prior.

    BUG FIX: The full deduplicated pool (up to 16 entries) is used when
    searching for prior-year matches. Only the 8 most-recent entries are
    used as the 'current' quarters to yield YoY rates — this ensures a
    current Q (e.g. Q4 2025) can always find its prior-year partner
    (Q4 2024) even when the pool has many quarters.

    Returns (rates, labels, ends_out, prior_vals)."""

    pool = []

    for v, e in zip(fmp_vals or [], fmp_ends or []):

        if v is not None and e:

            pool.append({'val': float(v), 'end': e, 'src': 'FMP'})

    for v, e in zip(edgar_vals or [], edgar_ends or []):

        if v is not None and e:

            pool.append({'val': float(v), 'end': e, 'src': 'EDGAR'})

    pool.sort(key=lambda x: x['end'], reverse=True)

    # Build full deduped list (no cap yet) — needed so prior-year quarters
    # are always reachable even when there are many quarters in the pool.
    deduped_full = []

    for entry in pool:

        duplicate = False

        for kept in deduped_full:

            try:

                d1 = datetime.strptime(entry['end'], '%Y-%m-%d').date()

                d2 = datetime.strptime(kept['end'],  '%Y-%m-%d').date()

                if abs((d1 - d2).days) <= 45:

                    duplicate = True

                    if entry['src'] == 'FMP' and kept['src'] == 'EDGAR':

                        deduped_full.remove(kept)

                        deduped_full.append(entry)

                    break

            except Exception:

                pass

        if not duplicate:

            deduped_full.append(entry)

    # 'current' quarters: only 8 most-recent (what we produce YoY rates for)
    deduped_curr = deduped_full[:8]

    # Keep newest-first for prior-year search; will build rates in any order

    rates, labels, ends_out, prior_vals = [], [], [], []

    seen_ends = set()  # avoid duplicate rate entries for same date

    for curr in deduped_curr:

        try:

            curr_dt = datetime.strptime(curr['end'], '%Y-%m-%d').date()

        except Exception:

            continue

        # Target: exactly 1 year ago; handle Feb 29 edge case

        try:

            target_dt = curr_dt.replace(year=curr_dt.year - 1)

        except ValueError:

            target_dt = curr_dt - timedelta(days=365)

        # Search the FULL pool for prior-year — not just the capped 8 —
        # so older quarters (e.g. Q4 2024 when pool has 12 entries) are found.
        prior = None

        best_diff = 32

        for candidate in deduped_full:

            if candidate['end'] == curr['end']:

                continue

            if candidate['src'] != curr['src']:

                continue

            try:

                cand_dt = datetime.strptime(candidate['end'], '%Y-%m-%d').date()

                diff = abs((cand_dt - target_dt).days)

                if diff < best_diff:

                    best_diff = diff

                    prior = candidate

            except Exception:

                pass

        if prior is None or prior['val'] == 0:

            continue

        if curr['end'] in seen_ends:

            continue

        seen_ends.add(curr['end'])

        rate = (curr['val'] - prior['val']) / abs(prior['val']) * 100

        try:

            dt    = datetime.strptime(curr['end'], '%Y-%m-%d').date()

            label = f"Q{(dt.month + 2) // 3} {dt.year}"

        except Exception:

            label = curr['end']

        rates.append(rate)

        labels.append(label)

        ends_out.append(curr['end'])

        prior_vals.append(prior['val'])  # track prior-year value for negative-base flag

    # Sort chronologically (oldest first)

    combined = sorted(zip(ends_out, rates, labels, prior_vals), key=lambda x: x[0])

    if combined:

        ends_out, rates, labels, prior_vals = zip(*combined)

        return list(rates), list(labels), list(ends_out), list(prior_vals)

    return [], [], [], []





@st.cache_data(ttl=3600, show_spinner=False)

def get_code33_data(ticker: str) -> dict:

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

        lbls = [f"Q{(d.month + 2)//3} {d.year}" for d, _ in rows]

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

            rev_lbls = [f"Q{(r['dt'].month + 2)//3} {r['dt'].year}" for r in rows]

            rev_fy   = [r['fy']  for r in rows]

            rev_fp   = [r['fp']  for r in rows]



            # Net income absolute values

            ni_vals, ni_lbls, ni_ends, ni_fy, ni_fp = [], [], [], [], []

            for r in rows:

                if r['ni'] is not None:

                    ni_vals.append(r['ni'])

                    ni_lbls.append(f"Q{(r['dt'].month + 2)//3} {r['dt'].year}")

                    ni_ends.append(r['dt'].isoformat())

                    ni_fy.append(r['fy'])

                    ni_fp.append(r['fp'])



            # Compute quarterly margin % = netIncome / revenue * 100

            margin_vals, margin_lbls, margin_ends = [], [], []

            for r in rows:

                if r['ni'] is not None and r['rev'] != 0:

                    margin_vals.append(r['ni'] / r['rev'] * 100)

                    margin_lbls.append(f"Q{(r['dt'].month + 2)//3} {r['dt'].year}")

                    margin_ends.append(r['dt'].isoformat())



            # EPS (diluted preferred)

            eps_vals, eps_lbls, eps_ends, eps_fy, eps_fp = [], [], [], [], []

            for r in rows:

                if r['eps'] is not None:

                    eps_vals.append(r['eps'])

                    eps_lbls.append(f"Q{(r['dt'].month + 2)//3} {r['dt'].year}")

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

        lbls = [f"Q{(e['dt'].month + 2) // 3} {e['dt'].year}" for e in deduped]

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



        for concept in concepts:

            entries = usgaap.get(concept, {}).get('units', {}).get(unit, [])

            if not entries:

                continue



            dedup_by_end = {}

            for e in entries:

                form = str(e.get('form', '')).strip().upper()

                if form not in ('10-Q', '10-K'):

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



                duration_days = (end_dt - start_dt).days

                if duration_days < 80 or duration_days > 105:

                    continue



                try:

                    filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date() if filed_str else None

                except Exception:

                    filed_dt = None



                current = dedup_by_end.get(end_dt)

                if current is None or (filed_dt is not None and (current.get('_filed_dt') is None or filed_dt > current.get('_filed_dt'))):

                    cloned = dict(e)

                    cloned['_end_dt'] = end_dt

                    cloned['_filed_dt'] = filed_dt

                    cloned['_val'] = float(val)

                    # Normalise fp to uppercase; derive fy from end_date (not EDGAR's filing year)

                    raw_fp = str(e.get('fp', '')).upper().strip()

                    if raw_fp in ('Q1', 'Q2', 'Q3', 'Q4'):

                        cloned['_fp'] = raw_fp

                        cloned['_fy'] = end_dt.year  # use period year, not filing year

                    elif raw_fp == 'FY' and 80 <= duration_days <= 105:

                        cloned['_fp'] = 'Q4'  # 10-K covering only Q4 period (fiscal-year companies)

                        cloned['_fy'] = end_dt.year

                    else:

                        cloned['_fp'] = None

                        cloned['_fy'] = int(e['fy']) if e.get('fy') is not None else None

                    dedup_by_end[end_dt] = cloned



            # For 10-K entries, only keep if end_date is more recent than latest 10-Q

            latest_10q_end = max(

                (v['_end_dt'] for v in dedup_by_end.values() if str(v.get('form','')).strip().upper() == '10-Q'),

                default=None

            )

            if latest_10q_end is not None:

                dedup_by_end = {

                    k: v for k, v in dedup_by_end.items()

                    if str(v.get('form','')).strip().upper() == '10-Q'

                    or v['_end_dt'] > latest_10q_end

                }



            filtered_entries = sorted(dedup_by_end.values(), key=lambda x: x['_end_dt'], reverse=True)

            filtered_entries = filtered_entries[:8]



            if len(filtered_entries) < 3:

                continue

            if filtered_entries[0]['_end_dt'] < recency_cutoff:

                continue



            filtered_entries.reverse()  # chronological ascending



            # Derive ALL missing Q4s from 10-K annual filings

            # Collect all 10-K annual entries first

            annual_entries = []

            for e in entries:

                if str(e.get('form', '')).strip().upper() != '10-K':

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

                duration = (end_dt - start_dt).days

                if 350 <= duration <= 380:

                    annual_fy = int(e['fy']) if e.get('fy') is not None else None

                    annual_entries.append((end_dt, start_dt, float(val), annual_fy))

            

            # For each annual entry, check if Q4 is missing and derive it

            existing_ends = {item['_end_dt'] for item in filtered_entries}

            for annual_end, annual_start, annual_val, annual_fy in annual_entries:

                # Check if a quarterly entry already exists near this annual end date

                already_exists = any(

                    abs((annual_end - existing_end).days) <= 45

                    for existing_end in existing_ends

                )

                if already_exists:

                    continue

                # Find Q1+Q2+Q3 within this fiscal year

                # Search the UNCAPPED quarterly pool so that older Q1+Q2+Q3

                # are not missed when filtered_entries was already capped at 8.

                q_in_year = [

                    item for item in dedup_by_end.values()

                    if item['_end_dt'] > annual_start and item['_end_dt'] <= annual_end

                ]

                if len(q_in_year) == 3:

                    q4_val = annual_val - sum(item['_val'] for item in q_in_year)

                    derived = {

                        '_end_dt': annual_end,

                        '_filed_dt': None,

                        '_val': q4_val,

                        'form': '10-K-derived',

                        '_fy': annual_fy,

                        '_fp': 'Q4',

                    }

                    filtered_entries.append(derived)

                    existing_ends.add(annual_end)

            

            # Re-sort after adding derived entries

            filtered_entries.sort(key=lambda x: x['_end_dt'])



            vals    = [item['_val'] for item in filtered_entries]

            ends    = [item['_end_dt'].isoformat() for item in filtered_entries]

            lbls    = [f"Q{(item['_end_dt'].month + 2) // 3} {item['_end_dt'].year}" for item in filtered_entries]

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



    # ── Revenue YoY ───────────────────────────────────────────────────────────

    rev_yoy_final, rev_labels_final, _, _rev_prior_vals = _date_first_yoy(

        fmp_rev, fmp_rev_end, edgar_rev, edgar_rev_end

    )

    rev_raw_final      = edgar_rev     if edgar_rev     else fmp_rev

    rev_raw_ends_final = edgar_rev_end if edgar_rev     else fmp_rev_end

    sources['rev'] = 'FMP|EDGAR' if rev_yoy_final else 'insufficient'



    # ── Net Profit Margin pool (replaces NI YoY) ─────────────────────────────

    npm_vals, npm_labels_final, npm_ends_final = _build_margin_pool(

        fmp_rev, fmp_rev_end, fmp_ni, fmp_ni_end,

        edgar_rev, edgar_rev_end, edgar_ni_abs, edgar_ni_end

    )

    ni_raw_final      = edgar_ni_abs if edgar_ni_abs else fmp_ni

    ni_raw_ends_final = edgar_ni_end if edgar_ni_abs else fmp_ni_end

    sources['ni'] = 'FMP|EDGAR' if npm_vals else 'insufficient'



    # -- EPS YoY (BUG 2 FIX: Finnhub=primary adjusted, FMP=secondary, EDGAR=fallback)

    # _date_first_yoy enforces strict source lock: same-source YoY pairs only.

    eps_fh_clean = _sane_eps(fh_eps)



    # Pass 1: Finnhub vs FMP (each source pairs only with itself inside the pool)

    eps_yoy_final, eps_labels_final, eps_yoy_ends, eps_prior_vals = _date_first_yoy(

        eps_fh_clean, fh_eps_end, eps_fmp_clean, fmp_eps_end

    )

    # Pass 2: if < 3 YoY points, also attempt Finnhub vs EDGAR

    if len(eps_yoy_final) < 3:

        eps_yoy_e2, eps_labels_e2, eps_ends_e2, eps_prior_e2 = _date_first_yoy(

            eps_fh_clean, fh_eps_end, eps_edgar_clean, edgar_eps_end

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



# ── Financial statements (EDGAR primary, yfinance fallback) ───────────────────



@st.cache_data(ttl=3600, show_spinner=False)

def get_edgar_financials(ticker: str) -> dict:

    """

    Returns {income_q, income_a, balance_q, balance_a, cf_q, cf_a}.

    DataFrames: rows=metrics, cols=dates ASCENDING (oldest first = LEFT).

    """

    facts = get_edgar_facts(ticker)

    yf    = get_financials(ticker)



    def _ts(series: dict) -> pd.Series:

        return pd.Series({pd.Timestamp(k): v for k, v in series.items()})



    def _edgar_df(concept_rows, quarterly, balance=False):

        try:

            data = {}

            for name, concepts, _ in concept_rows:

                s = _edgar_series(facts, concepts, quarterly=quarterly, balance=balance)

                if s: data[name] = _ts(s)

            if not data: return None

            df = pd.DataFrame(data).T

            df = df.sort_index(axis=1, ascending=True)   # oldest LEFT

            return df

        except Exception:

            return None



    def _yf_df(yf_key, concept_rows):

        try:

            df_yf = yf.get(yf_key)

            if df_yf is None or not isinstance(df_yf, pd.DataFrame) or df_yf.empty:

                return pd.DataFrame()

            result = {}

            for name, _, yf_keys in concept_rows:

                for k in yf_keys:

                    if k in df_yf.index:

                        result[name] = df_yf.loc[k]

                        break

            if len(result) == 0: return pd.DataFrame()

            out = pd.DataFrame(result).T

            out = out.sort_index(axis=1, ascending=True)  # oldest LEFT

            return out

        except Exception:

            return pd.DataFrame()



    IS_CONCEPTS = [

        ('Revenue',           ['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax'],

                              ['Total Revenue','Revenue']),

        ('Cost of Revenue',   ['CostOfRevenue','CostOfGoodsAndServicesSold'],

                              ['Cost Of Revenue','Cost Of Goods Sold']),

        ('Gross Profit',      ['GrossProfit'],

                              ['Gross Profit']),

        ('R&D',               ['ResearchAndDevelopmentExpense'],

                              ['Research And Development','Research And Development Expenses']),

        ('SG&A',              ['SellingGeneralAndAdministrativeExpense'],

                              ['Selling General And Administration','Selling General Administrative']),

        ('Operating Income',  ['OperatingIncomeLoss'],

                              ['Operating Income','EBIT']),

        ('D&A',               ['DepreciationDepletionAndAmortization','DepreciationAndAmortization'],

                              ['Depreciation And Amortization','Depreciation Amortization Depletion']),

        ('Interest Expense',  ['InterestExpense','InterestAndDebtExpense'],

                              ['Interest Expense']),

        ('Pretax Income',     ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'],

                              ['Pretax Income','Earnings Before Tax']),

        ('Tax Expense',       ['IncomeTaxExpenseBenefit'],

                              ['Tax Provision','Income Tax Expense']),

        ('Net Income',        ['NetIncomeLoss'],

                              ['Net Income','Net Income Common Stockholders']),

        ('EPS Diluted',       ['EarningsPerShareDiluted'],

                              ['Diluted EPS']),

        ('EPS Basic',         ['EarningsPerShareBasic'],

                              ['Basic EPS']),

    ]

    BS_CONCEPTS = [

        ('Cash & Equivalents',         ['CashAndCashEquivalentsAtCarryingValue','CashCashEquivalentsAndShortTermInvestments'],

                                       ['Cash And Cash Equivalents','Cash Financial']),

        ('Short-term Investments',     ['ShortTermInvestments','AvailableForSaleSecuritiesCurrent'],

                                       ['Other Short Term Investments','Short Term Investments']),

        ('Accounts Receivable',        ['AccountsReceivableNetCurrent'],

                                       ['Net Receivables','Accounts Receivable']),

        ('Inventory',                  ['InventoryNet'],

                                       ['Inventory']),

        ('Total Current Assets',       ['AssetsCurrent'],

                                       ['Current Assets','Total Current Assets']),

        ('PP&E',                       ['PropertyPlantAndEquipmentNet'],

                                       ['Net PPE','Property Plant And Equipment Net']),

        ('Goodwill',                   ['Goodwill'],

                                       ['Goodwill']),

        ('Intangibles',                ['FiniteLivedIntangibleAssetsNet','IndefiniteLivedIntangibleAssetsExcludingGoodwill'],

                                       ['Other Intangible Assets','Intangible Assets']),

        ('Total Assets',               ['Assets'],

                                       ['Total Assets']),

        ('Accounts Payable',           ['AccountsPayableCurrent'],

                                       ['Accounts Payable']),

        ('Total Current Liabilities',  ['LiabilitiesCurrent'],

                                       ['Current Liabilities','Total Current Liabilities']),

        ('Long-term Debt',             ['LongTermDebt','LongTermDebtNoncurrent'],

                                       ['Long Term Debt','Long Term Debt And Capital Lease Obligation']),

        ('Total Liabilities',          ['Liabilities'],

                                       ['Total Liabilities Net Minority Interest','Total Liabilities']),

        ('Total Equity',               ['StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],

                                       ['Stockholders Equity','Common Stock Equity']),

    ]

    CF_CONCEPTS = [

        ('Operating Cash Flow',  ['NetCashProvidedByUsedInOperatingActivities'],

                                 ['Operating Cash Flow']),

        ('Capital Expenditure',  ['PaymentsToAcquirePropertyPlantAndEquipment'],

                                 ['Capital Expenditure']),

        ('Investing Activities', ['NetCashProvidedByUsedInInvestingActivities'],

                                 ['Investing Cash Flow','Net Cash Used In Investing Activities']),

        ('Share Buybacks',       ['PaymentsForRepurchaseOfCommonStock'],

                                 ['Repurchase Of Capital Stock']),

        ('Dividends Paid',       ['PaymentsOfDividends','PaymentsOfDividendsCommonStock'],

                                 ['Payment Of Dividends','Cash Dividends Paid']),

        ('Financing Activities', ['NetCashProvidedByUsedInFinancingActivities'],

                                 ['Financing Cash Flow','Net Cash Used In Financing Activities']),

        ('Net Change in Cash',   ['CashCashEquivalentsAndRestrictedCashPeriodIncreaseDecreaseIncludingExchangeRateEffect',

                                   'CashAndCashEquivalentsPeriodIncreaseDecrease'],

                                 ['Changes In Cash','Net Change In Cash']),

    ]



    out = {}

    for period, quarterly in [('q', True), ('a', False)]:

        yf_sfx = 'quarterly' if quarterly else 'annual'



        e_is = _edgar_df(IS_CONCEPTS, quarterly=quarterly)

        out[f'income_{period}'] = e_is if e_is is not None and len(e_is.columns) >= 3 \
            else _yf_df(f'income_{yf_sfx}', IS_CONCEPTS)



        e_bs = _edgar_df(BS_CONCEPTS, quarterly=quarterly, balance=True)

        out[f'balance_{period}'] = e_bs if e_bs is not None and len(e_bs.columns) >= 3 \
            else _yf_df(f'balance_{yf_sfx}', BS_CONCEPTS)



        e_cf = _edgar_df(CF_CONCEPTS, quarterly=quarterly)

        out[f'cf_{period}'] = e_cf if e_cf is not None and len(e_cf.columns) >= 3 \
            else _yf_df(f'cashflow_{yf_sfx}', CF_CONCEPTS)



    return out



# ── News ──────────────────────────────────────────────────────────────────────



@st.cache_data(ttl=300, show_spinner=False)

def fetch_stock_news(ticker: str) -> list:

    items = []; seen: set = set()

    clean = ticker.upper().split('.')[0]

    if _HAS_FINNHUB:

        today = datetime.now().strftime('%Y-%m-%d')

        week  = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

        try:

            r = requests.get('https://finnhub.io/api/v1/company-news',

                             params={'symbol': clean, 'from': week, 'to': today, 'token': FINNHUB_KEY}, timeout=8)

            for art in r.json():

                h = (art.get('headline') or '').strip()

                if h and h not in seen:

                    seen.add(h)

                    items.append({'title': h, 'source': art.get('source','Finnhub'),

                                  'published': _time_ago(art.get('datetime')), 'link': art.get('url','')})

        except Exception:

            pass

    try:

        if _HAS_ALPACA and ALPACA_KEY:

            r = requests.get('https://data.alpaca.markets/v1beta1/news',

                             params={'symbols': clean, 'limit': 30, 'sort': 'desc', 'include_content': 'false'},

                             auth=(ALPACA_KEY, ALPACA_SECRET), timeout=8)

            for art in r.json().get('news', []):

                h = (art.get('headline') or '').strip()

                if h and h not in seen:

                    seen.add(h)

                    items.append({'title': h, 'source': art.get('source','Alpaca'),

                                  'published': _time_ago(art.get('created_at') or art.get('updated_at','')),

                                  'link': art.get('url','')})

    except Exception:

        pass

    return items[:50]



# ── Financial table renderer ──────────────────────────────────────────────────

# Columns are ASCENDING (oldest=left, newest=right).

# Growth for col[i] = change vs col[i-1]; col[0] shows "—".



def _render_fin_table(df: pd.DataFrame, rows_spec: list, title: str,

                      chart_metric: str | None = None, chart_type: str = 'Bar'):

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:

        st.warning(f"{title}: Data unavailable.")

        return



    cols_all  = list(df.columns)[:8]       # oldest first (ascending sort)

    date_strs = [str(c)[:7] for c in cols_all]  # e.g. 2024-03



    # ── Mini chart ──

    if chart_metric and chart_metric in df.index and len(cols_all) > 1:

        vals = [_sf(df.loc[chart_metric, c]) for c in cols_all]  # already oldest→newest

        if any(v is not None for v in vals):

            fig = go.Figure()

            if chart_type == 'Bar':

                colors = [GREEN if (v or 0) >= 0 else RED for v in vals]

                fig.add_trace(go.Bar(x=date_strs, y=vals, marker_color=colors,

                                     text=[_fmt_cell(v) if v is not None else '' for v in vals],

                                     textposition='outside', textfont_color='white'))

            else:

                fig.add_trace(go.Scatter(x=date_strs, y=vals,

                                         line=dict(color=GREEN, width=2),

                                         fill='tozeroy', fillcolor='rgba(0,255,65,0.06)'))

            fig.update_layout(paper_bgcolor=DARK, plot_bgcolor=BG, height=160,

                              margin=dict(t=5,b=5,l=5,r=5),

                              yaxis=dict(gridcolor='#222', color=GRAY, tickfont_size=9),

                              xaxis=dict(color=GRAY, tickfont_size=9),

                              font=dict(color='white', family='Courier New'),

                              showlegend=False,

                              title=dict(text=chart_metric, font=dict(color=GRAY, size=11)))

            st.plotly_chart(fig, use_container_width=True)



    # ── HTML table ──

    hcols = ''.join(f'<th style="text-align:right;color:{GRAY};font-size:11px;padding:4px 8px;">{d}</th>'

                    for d in date_strs)

    html  = (f'<div style="overflow-x:auto;margin-bottom:20px;">'

             f'<table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">'

             f'<thead><tr>'

             f'<th style="text-align:left;color:{GRAY};font-size:11px;padding:4px 8px;min-width:180px;">{title}</th>'

             f'{hcols}</tr></thead><tbody>')



    def _row_vals(row_name):

        return [_sf(df.loc[row_name, c]) for c in cols_all]



    def _render_data_row(label, raw, bold=False, indent=False, is_pct=False):

        cells = []

        for i, v in enumerate(raw):

            if is_pct:

                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(v, is_pct=True, already_pct=True)}</td>')

            else:

                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(v)}</td>')

        lbl = ('&nbsp;&nbsp;' if indent else '') + label

        fw  = 'font-weight:bold;' if bold else ''

        return (f'<tr style="border-top:1px solid #1a1a1a;">'

                f'<td style="padding:4px 8px;{fw}">{lbl}</td>' + ''.join(cells) + '</tr>\n')



    def _render_growth_row(label, raw):

        """Growth: col[i] vs col[i-1]. col[0] → —."""

        cells = []

        for i, v in enumerate(raw):

            if i == 0:

                cells.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')

            else:

                cells.append(f'<td style="text-align:right;padding:4px 8px;">{_growth_cell(raw[i], raw[i-1])}</td>')

        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'

        return (f'<tr style="border-top:1px solid #1a1a1a;">'

                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')



    def _render_margin_row(label, num_row, denom_row='Revenue'):

        if num_row not in df.index or denom_row not in df.index: return ''

        cells = []

        for c in cols_all:

            cells.append(f'<td style="text-align:right;padding:4px 8px;">'

                         f'{_pct_cell(df.loc[num_row, c], df.loc[denom_row, c])}</td>')

        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'

        return (f'<tr style="border-top:1px solid #1a1a1a;">'

                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')



    def _render_ratio_row(label, num_row, denom_row, negate_num=False):

        if num_row not in df.index or denom_row not in df.index: return ''

        cells = []

        for c in cols_all:

            n = _sf(df.loc[num_row, c]); d = _sf(df.loc[denom_row, c])

            if n is None or d is None or d == 0:

                cells.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')

            else:

                if negate_num: n = -n

                v = n / d

                c_color = GRAY

                cells.append(f'<td style="text-align:right;padding:4px 8px;color:{c_color}">{v:.2f}x</td>')

        lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'

        return (f'<tr style="border-top:1px solid #1a1a1a;">'

                f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')



    def _render_computed_row(label, row_fn):

        """row_fn(cols_all) -> list of formatted td strings."""

        try:

            cells = row_fn(cols_all)

            lbl = f'<span style="color:{GRAY};font-size:11px;">&nbsp;&nbsp;{label}</span>'

            return (f'<tr style="border-top:1px solid #1a1a1a;">'

                    f'<td style="padding:4px 8px;">{lbl}</td>' + ''.join(cells) + '</tr>\n')

        except Exception:

            return ''



    for row_name, row_type in rows_spec:

        if row_type == 'section_header':

            html += (f'<tr><td colspan="{len(cols_all)+1}" style="padding:8px 6px 2px 6px;'

                     f'color:{GRAY};font-size:10px;letter-spacing:1px;border-top:1px solid #222;">'

                     f'{row_name}</td></tr>\n')

            continue



        # ── Computed rows that don't need the metric in df.index ──

        if row_type == 'ebitda':

            def _ebitda_cells(cols):

                out = []

                for c in cols:

                    oi = _sf(df.loc['Operating Income', c]) if 'Operating Income' in df.index else None

                    da = _sf(df.loc['D&A', c]) if 'D&A' in df.index else None

                    if oi is not None and da is not None:

                        out.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(oi + abs(da))}</td>')

                    else:

                        out.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')

                return out

            html += _render_computed_row('EBITDA', _ebitda_cells)

            continue



        if row_type == 'free_cf':

            def _fcf_cells(cols):

                out = []

                for c in cols:

                    ocf = _sf(df.loc['Operating Cash Flow', c]) if 'Operating Cash Flow' in df.index else None

                    cx  = _sf(df.loc['Capital Expenditure', c]) if 'Capital Expenditure' in df.index else None

                    if ocf is not None and cx is not None:

                        out.append(f'<td style="text-align:right;padding:4px 8px;">{_fmt_cell(ocf - abs(cx))}</td>')

                    else:

                        out.append(f'<td style="text-align:right;padding:4px 8px;"><span style="color:#555">—</span></td>')

                return out

            html += _render_computed_row('Free Cash Flow', _fcf_cells)

            continue



        if row_type == 'de_ratio':

            html += _render_ratio_row('Debt-to-Equity', 'Long-term Debt', 'Total Equity')

            continue



        if row_type == 'tax_rate':

            html += _render_margin_row('Tax Rate%', 'Tax Expense', 'Pretax Income')

            continue



        if row_type == 'gross_margin':

            html += _render_margin_row('Gross Margin%', 'Gross Profit', 'Revenue')

            continue



        if row_type == 'op_margin':

            html += _render_margin_row('Operating Margin%', 'Operating Income', 'Revenue')

            continue



        if row_type == 'net_margin':

            html += _render_margin_row('Net Margin%', 'Net Income', 'Revenue')

            continue



        # ── Rows that need the metric in df.index ──

        if row_name not in df.index:

            # Row not found — show blank row so structure stays intact

            cells = ''.join(f'<td style="text-align:right;padding:4px 8px;color:#555">N/A</td>' for _ in cols_all)

            lbl = ('&nbsp;&nbsp;' if row_type not in ('bold',) else '') + row_name

            html += (f'<tr style="border-top:1px solid #1a1a1a;opacity:0.5;">'

                     f'<td style="padding:4px 8px;">{lbl}</td>{cells}</tr>\n')

            continue



        raw = _row_vals(row_name)



        if row_type in ('bold', 'raw'):

            html += _render_data_row(row_name, raw, bold=(row_type == 'bold'))

        elif row_type == 'indent':

            html += _render_data_row(row_name, raw, indent=True)

        elif row_type == 'growth':

            html += _render_growth_row(f'{row_name} Growth%', raw)

        elif row_type == 'bold_growth':

            html += _render_data_row(row_name, raw, bold=True)

            html += _render_growth_row(f'{row_name} Growth%', raw)



    html += '</tbody></table></div>'

    st.markdown(html, unsafe_allow_html=True)



# ── Code 33 computation ───────────────────────────────────────────────────────



def _parse_end_date(end_date: str):

    try:

        dt = datetime.strptime(str(end_date), '%Y-%m-%d').date()

        q = (dt.month + 2) // 3

        return dt.year, q

    except Exception:

        return None



def _compute_yoy(vals: list, end_dates: list, srcs=None) -> list:

    """

    Date-based YoY: for each quarter, find the same quarter

    from ~1 year ago by looking for an end_date within 45 days

    of (this_date - 365 days). Works for all fiscal calendars.

    Prefers same-source prior-year match when srcs provided.

    """

    if not vals or not end_dates:

        return []



    n = min(len(vals), len(end_dates))



    # Build lookup: date -> (value, source)

    date_src_val_map = {}

    for i in range(n):

        if vals[i] is not None and end_dates[i] is not None:

            try:

                dt = datetime.strptime(end_dates[i], '%Y-%m-%d').date()

                date_src_val_map[dt] = (float(vals[i]), srcs[i] if srcs and i < len(srcs) else 'unknown')

            except Exception:

                pass



    rates = []

    for i in range(n):

        if vals[i] is None or end_dates[i] is None:

            rates.append(None)

            continue

        try:

            current_dt  = datetime.strptime(end_dates[i], '%Y-%m-%d').date()

            current_val = float(vals[i])

        except Exception:

            rates.append(None)

            continue



        # Look for prior year quarter: end_date within 45 days of current - 365

        # Use timedelta(days=365) to safely handle Feb 29 leap-year dates

        try:

            target_dt = current_dt.replace(year=current_dt.year - 1)

        except ValueError:

            from datetime import timedelta

            target_dt = current_dt - timedelta(days=365)



        current_src = srcs[i] if srcs and i < len(srcs) else 'unknown'

        prior_val  = None

        best_diff  = 46  # must be within 45 days

        for dt, (v, src) in date_src_val_map.items():

            diff = abs((dt - target_dt).days)

            if diff < best_diff:

                if src == current_src or prior_val is None:

                    best_diff = diff

                    prior_val = v

                elif diff < best_diff - 5:

                    best_diff = diff

                    prior_val = v



        if prior_val is None or prior_val == 0:

            rates.append(None)

            continue



        rate = (current_val - prior_val) / abs(prior_val) * 100

        # Cap at ±500% to avoid display issues

        rates.append(max(min(rate, 500.0), -500.0))



    return rates



def _last3_valid_with_labels(rates: list, labels: list) -> tuple:

    """Return last 3 valid (rate, label) pairs."""

    pairs = [(r, labels[i] if i < len(labels) else None) for i, r in enumerate(rates) if r is not None]

    if len(pairs) < 3:

        return [], []

    last = pairs[-3:]

    return [p[0] for p in last], [p[1] for p in last]



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



def _dc(d):

    if d is None: return GRAY

    return GREEN if d > 0 else (RED if d < 0 else YELLOW)



def _rate_badge(r):

    if r is None: return f'<span style="color:{GRAY}">N/A</span>'

    c = GREEN if r > 0 else RED

    return f'<span style="color:{c};font-weight:bold;">{r:+,.1f}%</span>'



def _delta_badge(d):

    if d is None: return f'<span style="color:{GRAY}">—</span>'

    c = _dc(d); arrow = '▲' if d > 0 else ('▼' if d < 0 else '■')

    return f'<span style="color:{c}">{arrow} {"+" if d>=0 else ""}{d:.1f} pp</span>'



# ── Analyst estimate fetch ────────────────────────────────────────────────────



@st.cache_data(ttl=3600, show_spinner=False)

def get_analyst_estimates(ticker: str) -> dict:

    """Forward EPS estimates. yfinance primary, Finnhub fallback."""

    result = {'rows': [], 'source': ''}

    try:

        import yfinance as yf

        t = yf.Ticker(ticker)

        ee = t.earnings_estimate

        if isinstance(ee, pd.DataFrame) and not ee.empty:

            label_map = {

                '0q': 'Current Quarter', '+1q': 'Next Quarter',

                '0y': 'Current Year',   '+1y': 'Next Year',

            }

            for idx in ee.index:

                label = label_map.get(str(idx), str(idx))

                avg    = _sf(ee.loc[idx, 'avg'])       if 'avg'             in ee.columns else None

                low    = _sf(ee.loc[idx, 'low'])       if 'low'             in ee.columns else None

                high   = _sf(ee.loc[idx, 'high'])      if 'high'            in ee.columns else None

                n_ana  = _sf(ee.loc[idx, 'numberOfAnalysts']) if 'numberOfAnalysts' in ee.columns else None

                yago   = _sf(ee.loc[idx, 'yearAgoEps']) if 'yearAgoEps'     in ee.columns else None

                growth = _sf(ee.loc[idx, 'growth'])    if 'growth'          in ee.columns else None

                result['rows'].append({

                    'label': label, 'avg': avg, 'low': low, 'high': high,

                    'n': n_ana, 'yago': yago, 'growth': growth,

                })

            result['source'] = 'yfinance'

            return result

    except Exception:

        pass

    # Finnhub fallback: basic financials has some forward data

    if _HAS_FINNHUB:

        try:

            bf = fh_basic_financials(ticker.upper())

            if isinstance(bf, dict):

                m = bf.get('metric', {})

                for label, key in [('EPS Forward', 'epsForwardTTM')]:

                    v = _sf(m.get(key))

                    if v: result['rows'].append({'label': label, 'avg': v})

                result['source'] = 'Finnhub'

        except Exception:

            pass

    return result



# ── Main page ─────────────────────────────────────────────────────────────────



ticker = render_sidebar()

st.markdown("## 📋 Stock Detail")



if not ticker:

    st.info("Enter a ticker symbol in the sidebar to begin.")

    st.stop()



is_us = '.' not in ticker and not ticker.startswith('^')



with st.spinner(f"Loading {ticker} …"):

    try:    info    = get_ticker_info(ticker)

    except: info    = {}

    try:    bars_3y = get_price_history(ticker, period='3y', interval='1d')

    except: bars_3y = pd.DataFrame()

    try:    snaps   = get_snapshots((ticker.upper(),)) if is_us and _HAS_ALPACA else {}

    except: snaps   = {}

    try:    fin     = get_edgar_financials(ticker)

    except: fin     = {}

    try:    yf_fin  = get_financials(ticker)

    except: yf_fin  = {}



snap = snaps.get(ticker.upper(), {}) if isinstance(snaps, dict) else {}



# ── Price ─────────────────────────────────────────────────────────────────────

price      = _sf(snap.get('price'))      or _sf(safe_get(info,'currentPrice')) or _sf(safe_get(info,'regularMarketPrice'))

prev_close = _sf(snap.get('prev_close')) or _sf(safe_get(info,'regularMarketPreviousClose'))

chg        = (price - prev_close) if (price is not None and prev_close is not None) else None

chg_pct    = (chg / prev_close * 100) if (chg is not None and prev_close is not None and prev_close != 0) else None



open_p = _sf(snap.get('open')) or _sf(safe_get(info,'open'))

high_p = _sf(snap.get('high')) or _sf(safe_get(info,'dayHigh'))

low_p  = _sf(snap.get('low'))  or _sf(safe_get(info,'dayLow'))

vol_p  = snap.get('volume')    or safe_get(info,'volume')



hi52 = lo52 = avg_vol = None

if bars_3y is not None and not bars_3y.empty:

    last_252 = bars_3y.tail(252)

    hi52 = _sf(last_252['High'].max()); lo52 = _sf(last_252['Low'].min())

    avg_vol = _sf(bars_3y['Volume'].tail(50).mean())

hi52    = hi52    or _sf(safe_get(info,'fiftyTwoWeekHigh'))

lo52    = lo52    or _sf(safe_get(info,'fiftyTwoWeekLow'))

avg_vol = avg_vol or _sf(safe_get(info,'averageVolume'))



name     = safe_get(info,'longName') or safe_get(info,'shortName') or ticker

exchange = safe_get(info,'exchange') or safe_get(info,'market') or ''

sector   = safe_get(info,'sector') or ''



# ── Header ────────────────────────────────────────────────────────────────────

chg_color = GREEN if (chg is not None and chg >= 0) else RED

price_str = f"${price:,.2f}" if price else "—"

chg_str   = (f"{'+'if chg>=0 else ''}{chg:.2f} ({chg_pct:+.2f}%)"

             if chg is not None and chg_pct is not None else "—")



st.markdown(f"""

<div style="background:{BG};border:1px solid #333;border-radius:8px;padding:20px 24px;margin-bottom:12px;">

  <div style="color:{GRAY};font-size:12px;font-family:monospace;letter-spacing:1px;">

    {ticker.upper()} &nbsp;·&nbsp; {exchange} &nbsp;·&nbsp; {sector}

  </div>

  <div style="color:#FFF;font-size:20px;font-weight:bold;margin:4px 0;">{name}</div>

  <div style="display:flex;align-items:baseline;gap:16px;margin-top:6px;">

    <span style="color:#FFF;font-size:36px;font-weight:bold;font-family:'Courier New',monospace;">{price_str}</span>

    <span style="color:{chg_color};font-size:18px;font-weight:bold;font-family:monospace;">{chg_str}</span>

  </div>

</div>""", unsafe_allow_html=True)



# ── OHLC Bar ──────────────────────────────────────────────────────────────────

def _oc(label, val, fn=None):

    v = fn(val) if fn and val else (f"${val:,.2f}" if val else "—")

    return (f'<div style="text-align:center;padding:8px 12px;">'

            f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'

            f'<div style="color:#FFF;font-size:14px;font-weight:bold;font-family:monospace;margin-top:3px;">{v}</div></div>')



sep = '<div style="width:1px;background:#333;margin:8px 0;"></div>'

st.markdown(f'''

<div style="background:{BG};border:1px solid #333;border-radius:6px;display:flex;flex-wrap:wrap;margin-bottom:16px;">

  {_oc("OPEN",open_p)}{sep}{_oc("HIGH",high_p)}{sep}{_oc("LOW",low_p)}{sep}

  {_oc("PREV CLOSE",prev_close)}{sep}{_oc("VOLUME",vol_p,fmt_volume)}{sep}

  {_oc("AVG VOL(50D)",avg_vol,fmt_volume)}{sep}{_oc("52W HIGH",hi52)}{sep}{_oc("52W LOW",lo52)}

</div>''', unsafe_allow_html=True)



# ── Price Chart ───────────────────────────────────────────────────────────────

range_opts = {'1D':1,'1W':7,'1M':30,'3M':90,'6M':180,'1Y':365}

sel_range  = st.radio('Range', list(range_opts.keys()), horizontal=True, index=3, label_visibility='collapsed')



chart_df = pd.DataFrame()

if bars_3y is not None and not bars_3y.empty:

    cutoff   = bars_3y.index[-1] - timedelta(days=range_opts[sel_range])

    chart_df = bars_3y[bars_3y.index >= cutoff].copy()



if not chart_df.empty:

    fp = _sf(chart_df['Close'].iloc[0]); lp = _sf(chart_df['Close'].iloc[-1])

    lc = GREEN if (fp and lp and lp >= fp) else RED

    rgb = ','.join(str(int(lc.lstrip('#')[i:i+2], 16)) for i in (0, 2, 4))

    fig = go.Figure()

    fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Close'],

                             line=dict(color=lc, width=2),

                             fill='tozeroy', fillcolor=f'rgba({rgb},0.08)',

                             hovertemplate='%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'))

    fig.update_layout(paper_bgcolor=DARK, plot_bgcolor=BG, height=320,

                      margin=dict(t=10,b=10,l=10,r=10),

                      yaxis=dict(gridcolor='#222', color=GRAY, tickprefix='$'),

                      xaxis=dict(color=GRAY, rangeslider=dict(visible=False)),

                      font=dict(color='white', family='Courier New'),

                      showlegend=False, hovermode='x unified')

    st.plotly_chart(fig, use_container_width=True)

else:

    st.warning("No price history available.")



st.markdown("---")



# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview","Financials","Earnings & Estimates","Code 33","News"])



# ════════════════════════════════════════════════════════════════════════════════

# TAB 1 — OVERVIEW

# ════════════════════════════════════════════════════════════════════════════════

with tab1:

    try:

        fhm = (fh_basic_financials(ticker.upper()) or {}).get('metric', {}) if _HAS_FINNHUB and is_us else {}

    except Exception:

        fhm = {}



    mkt_cap   = _sf(safe_get(info,'marketCap'))

    pe_ttm    = _sf(safe_get(info,'trailingPE'))     or _sf(fhm.get('peTTM'))

    pe_fwd    = _sf(safe_get(info,'forwardPE'))      or _sf(fhm.get('peForwardTTM'))

    eps_ttm   = _sf(safe_get(info,'trailingEps'))    or _sf(fhm.get('epsTTM'))

    rev_ttm   = _sf(safe_get(info,'totalRevenue'))   or _sf(fhm.get('revenueTTM'))

    gross_mgn = _sf(safe_get(info,'grossMargins'))   or _sf(fhm.get('grossMarginTTM'))

    net_mgn   = _sf(safe_get(info,'profitMargins'))  or _sf(fhm.get('netProfitMarginTTM'))

    beta      = _sf(safe_get(info,'beta'))           or _sf(fhm.get('beta'))

    roe       = _sf(safe_get(info,'returnOnEquity')) or _sf(fhm.get('roeTTM'))

    de_ratio  = _sf(safe_get(info,'debtToEquity'))   or _sf(fhm.get('totalDebt/totalEquityAnnual'))

    div_yield = _sf(safe_get(info,'dividendYield'))  or _sf(fhm.get('dividendYieldIndicatedAnnual'))

    float_sh  = _sf(safe_get(info,'floatShares'))



    def _card(label, value, fmt='num', suffix='', prefix=''):

        if value is None or _nan(value): disp, col = "N/A", GRAY

        elif fmt == 'large':   disp, col = fmt_large_number(value), '#FFF'

        elif fmt == 'pct':

            disp = f"{value*100:.1f}%"

            col  = GREEN if value > 0 else (RED if value < 0 else '#FFF')

        elif fmt == 'price':   disp, col = f"${value:,.2f}", '#FFF'

        elif fmt == 'shares':  disp, col = fmt_large_number(value, symbol=''), '#FFF'

        else:                  disp, col = f"{prefix}{value:,.2f}{suffix}", '#FFF'

        return (f'<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">'

                f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'

                f'<div style="color:{col};font-size:20px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{disp}</div></div>')



    r1a,r1b,r1c,r1d = st.columns(4)

    r1a.markdown(_card("MARKET CAP",    mkt_cap,  fmt='large'), unsafe_allow_html=True)

    r1b.markdown(_card("P/E TTM",       pe_ttm,   suffix='x'),  unsafe_allow_html=True)

    r1c.markdown(_card("P/E FORWARD",   pe_fwd,   suffix='x'),  unsafe_allow_html=True)

    r1d.markdown(_card("EPS TTM",       eps_ttm,  fmt='price'), unsafe_allow_html=True)

    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)



    r2a,r2b,r2c,r2d = st.columns(4)

    r2a.markdown(_card("REVENUE TTM",   rev_ttm,  fmt='large'), unsafe_allow_html=True)

    r2b.markdown(_card("GROSS MARGIN",  gross_mgn,fmt='pct'),   unsafe_allow_html=True)

    r2c.markdown(_card("NET MARGIN",    net_mgn,  fmt='pct'),   unsafe_allow_html=True)

    r2d.markdown(_card("BETA",          beta,     suffix=''),   unsafe_allow_html=True)

    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)



    r3a,r3b,r3c,r3d = st.columns(4)

    r3a.markdown(_card("ROE",           roe,      fmt='pct'),   unsafe_allow_html=True)

    de_disp = (de_ratio/100 if de_ratio and de_ratio > 10 else de_ratio)

    r3b.markdown(_card("DEBT/EQUITY",   de_disp,  suffix='x'),  unsafe_allow_html=True)

    r3c.markdown(_card("DIV YIELD",     div_yield,fmt='pct'),   unsafe_allow_html=True)

    r3d.markdown(_card("FLOAT SHARES",  float_sh, fmt='shares'),unsafe_allow_html=True)



    desc = safe_get(info,'longBusinessSummary') or ''

    if desc:

        st.markdown("<div style='margin:16px 0 4px 0'></div>", unsafe_allow_html=True)

        with st.expander("Company Description", expanded=False):

            st.markdown(f"<div style='color:#CCC;font-size:13px;line-height:1.6'>{desc}</div>",

                        unsafe_allow_html=True)



# ════════════════════════════════════════════════════════════════════════════════

# TAB 2 — FINANCIALS

# ════════════════════════════════════════════════════════════════════════════════

with tab2:

    c1, c2 = st.columns(2)

    with c1: period_sel    = st.radio("Period", ["Quarterly","Annual"], horizontal=True)

    with c2: chart_type_sel= st.radio("Chart",  ["Bar","Line"],         horizontal=True)



    pk = 'q' if period_sel == 'Quarterly' else 'a'



    income_df  = fin.get(f'income_{pk}',  pd.DataFrame())

    balance_df = fin.get(f'balance_{pk}', pd.DataFrame())

    cf_df      = fin.get(f'cf_{pk}',      pd.DataFrame())



    # ── Income Statement ──────────────────────────────────────────────────────

    st.markdown(f"### Income Statement <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",

                unsafe_allow_html=True)

    IS_ROWS = [

        ('Revenue',          'bold_growth'),

        ('Cost of Revenue',  'indent'),

        ('Gross Profit',     'raw'),

        ('gross_margin',     'gross_margin'),

        ('R&D',              'indent'),

        ('SG&A',             'indent'),

        ('Operating Income', 'raw'),

        ('op_margin',        'op_margin'),

        ('EBITDA',           'ebitda'),

        ('D&A',              'indent'),

        ('Interest Expense', 'indent'),

        ('Pretax Income',    'raw'),

        ('Tax Expense',      'indent'),

        ('tax_rate',         'tax_rate'),

        ('Net Income',       'bold'),

        ('net_margin',       'net_margin'),

        ('EPS Diluted',      'bold_growth'),

        ('EPS Basic',        'raw'),

    ]

    _render_fin_table(income_df, IS_ROWS, "Income Statement", 'Revenue', chart_type_sel)



    # ── Balance Sheet ─────────────────────────────────────────────────────────

    st.markdown(f"### Balance Sheet <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",

                unsafe_allow_html=True)

    BS_ROWS = [

        ('Cash & Equivalents',         'bold'),

        ('Short-term Investments',     'indent'),

        ('Accounts Receivable',        'indent'),

        ('Inventory',                  'indent'),

        ('Total Current Assets',       'raw'),

        ('PP&E',                       'indent'),

        ('Goodwill',                   'indent'),

        ('Intangibles',                'indent'),

        ('Total Assets',               'bold'),

        ('Accounts Payable',           'indent'),

        ('Total Current Liabilities',  'raw'),

        ('Long-term Debt',             'indent'),

        ('Total Liabilities',          'bold'),

        ('Total Equity',               'bold'),

        ('de_ratio',                   'de_ratio'),

    ]

    _render_fin_table(balance_df, BS_ROWS, "Balance Sheet", 'Total Assets', chart_type_sel)



    # ── Cash Flow ─────────────────────────────────────────────────────────────

    st.markdown(f"### Cash Flow <span style='color:{GRAY};font-size:13px'>({period_sel})</span>",

                unsafe_allow_html=True)

    CF_ROWS = [

        ('Operating Cash Flow',  'bold'),

        ('Capital Expenditure',  'indent'),

        ('Free Cash Flow',       'free_cf'),

        ('Investing Activities', 'raw'),

        ('Share Buybacks',       'indent'),

        ('Dividends Paid',       'indent'),

        ('Financing Activities', 'raw'),

        ('Net Change in Cash',   'bold'),

    ]

    _render_fin_table(cf_df, CF_ROWS, "Cash Flow", 'Operating Cash Flow', chart_type_sel)

    st.caption("Primary: SEC EDGAR · Fallback: yfinance · Oldest column = LEFT")



# ════════════════════════════════════════════════════════════════════════════════

# TAB 3 — EARNINGS & ESTIMATES

# ════════════════════════════════════════════════════════════════════════════════

with tab3:

    try:

        surprises = fh_earnings_surprises(ticker.upper()) if _HAS_FINNHUB and is_us else None

    except Exception:

        surprises = None



    # Next earnings date + countdown

    next_date = next_countdown = None

    try:

        import yfinance as yf_mod

        cal = yf_mod.Ticker(ticker).calendar

        if isinstance(cal, dict):

            ed = cal.get('Earnings Date')

            if isinstance(ed, list) and ed:    next_date = str(ed[0])[:10]

            elif ed is not None:               next_date = str(ed)[:10]

        elif isinstance(cal, pd.DataFrame) and not cal.empty:

            try: next_date = str(cal.loc['Earnings Date'].iloc[0])[:10]

            except Exception: pass

        if next_date:

            nd = datetime.strptime(next_date, '%Y-%m-%d')

            diff = (nd - datetime.now()).days

            next_countdown = f"{diff}d" if diff >= 0 else "Passed"

    except Exception:

        pass



    # Beat rates (last 8Q)

    last_date = eps_beat_rate = rev_beat_rate = None

    if isinstance(surprises, list) and len(surprises) > 0:

        last_date = surprises[0].get('period', '')

        last8 = surprises[:8]

        eps_b = sum(1 for s in last8 if (_sf(s.get('surprisePercent')) or 0) > 0)

        eps_beat_rate = eps_b / len(last8) * 100 if len(last8) > 0 else None



    # ── 4 Insight cards ──────────────────────────────────────────────────────

    def _ic(label, val, sub='', color='#FFF'):

        return (f'<div style="background:{BG};border:1px solid #2a2a2a;border-radius:6px;padding:14px 16px;">'

                f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:1px;">{label}</div>'

                f'<div style="color:{color};font-size:18px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:6px;">{val or "—"}</div>'

                f'{"<div style=color:"+GRAY+";font-size:11px;margin-top:2px>"+sub+"</div>" if sub else ""}'

                f'</div>')



    bc = GREEN if eps_beat_rate and eps_beat_rate >= 70 else (YELLOW if eps_beat_rate and eps_beat_rate >= 50 else RED)

    ic1,ic2,ic3,ic4 = st.columns(4)

    ic1.markdown(_ic("LAST REPORTED",      last_date or '—'), unsafe_allow_html=True)

    ic2.markdown(_ic("NEXT EARNINGS",      next_date or '—', sub=next_countdown or ''), unsafe_allow_html=True)

    ic3.markdown(_ic("EPS BEAT RATE (8Q)", f"{eps_beat_rate:.0f}%" if eps_beat_rate is not None else '—', color=bc), unsafe_allow_html=True)

    ic4.markdown(_ic("REV BEAT RATE (8Q)", "—"), unsafe_allow_html=True)



    st.markdown("<div style='margin:16px 0 8px 0'></div>", unsafe_allow_html=True)



    # ── Surprise table ───────────────────────────────────────────────────────

    if isinstance(surprises, list) and len(surprises) > 0:

        st.markdown(f"#### Earnings Surprise History")



        def _sv(v): # surprise value cell

            if v is None: return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'

            return f'<td style="text-align:right;padding:6px 10px;">{v:.2f}</td>'

        def _sc(pct): # surprise % cell colored

            if pct is None: return f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'

            c = GREEN if pct > 0 else RED

            return f'<td style="text-align:right;padding:6px 10px;color:{c};font-weight:bold;">{pct:+.1f}%</td>'



        rows_html = ''

        for s in surprises[:12]:

            qtr     = s.get('period','')

            eps_est = _sf(s.get('estimate'))

            eps_act = _sf(s.get('actual'))

            eps_sur = _sf(s.get('surprisePercent'))

            rows_html += (f'<tr style="border-bottom:1px solid #1a1a1a;">'

                          f'<td style="padding:6px 10px;color:{GRAY};font-family:monospace;">{qtr}</td>'

                          f'{_sv(eps_est)}{_sv(eps_act)}{_sc(eps_sur)}'

                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'

                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'

                          f'<td style="text-align:right;padding:6px 10px;color:{GRAY}">—</td>'

                          f'</tr>')



        hg = f'color:{GRAY};font-size:11px;padding:6px 10px;text-align:right'

        st.markdown(

            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px;">'

            f'<thead style="background:{BG}"><tr>'

            f'<th style="color:{GRAY};font-size:11px;padding:6px 10px;text-align:left">Quarter</th>'

            f'<th style="{hg}">EPS Est</th><th style="{hg}">EPS Actual</th>'

            f'<th style="{hg}">EPS Surp%</th>'

            f'<th style="{hg}">Rev Est</th><th style="{hg}">Rev Actual</th>'

            f'<th style="{hg}">Rev Surp%</th>'

            f'</tr></thead><tbody>{rows_html}</tbody></table></div>',

            unsafe_allow_html=True)

    else:

        st.info("Earnings surprise data unavailable (Finnhub).")



    # ── Analyst forward estimates ─────────────────────────────────────────────

    st.markdown("---")

    st.markdown("#### Analyst Forward EPS Estimates")

    try:

        est_data = get_analyst_estimates(ticker)

    except Exception:

        est_data = {'rows': [], 'source': ''}



    if est_data.get('rows'):

        eg = f'color:{GRAY};font-size:11px;padding:6px 12px;text-align:right'

        rows_e = ''

        for row in est_data['rows']:

            avg  = _sf(row.get('avg'))

            low  = _sf(row.get('low'))

            high = _sf(row.get('high'))

            n    = row.get('n')

            yago = _sf(row.get('yago'))

            grw  = _sf(row.get('growth'))

            def _ep(v): return f"${v:.2f}" if v is not None else "—"

            def _gp(v):

                if v is None: return "—"

                c = GREEN if v > 0 else RED

                return f'<span style="color:{c}">{v*100:+.1f}%</span>'

            rows_e += (f'<tr style="border-bottom:1px solid #1a1a1a">'

                       f'<td style="padding:6px 12px">{row.get("label","")}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{_ep(avg)}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{_ep(low)}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{_ep(high)}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{int(n) if n else "—"}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{_ep(yago)}</td>'

                       f'<td style="text-align:right;padding:6px 12px">{_gp(grw)}</td>'

                       f'</tr>')

        st.markdown(

            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:\'Courier New\',monospace;font-size:12px">'

            f'<thead style="background:{BG}"><tr>'

            f'<th style="color:{GRAY};font-size:11px;padding:6px 12px;text-align:left">Period</th>'

            f'<th style="{eg}">Avg EPS</th><th style="{eg}">Low</th><th style="{eg}">High</th>'

            f'<th style="{eg}">Analysts</th><th style="{eg}">Year-ago EPS</th><th style="{eg}">Growth%</th>'

            f'</tr></thead><tbody>{rows_e}</tbody></table></div>',

            unsafe_allow_html=True)

        st.caption(f"Source: {est_data.get('source','')}")

    else:

        st.info("Forward EPS estimates not available for this ticker.")



    st.caption("Surprise data: Finnhub · Estimates: yfinance / Finnhub")



# ════════════════════════════════════════════════════════════════════════════════

# TAB 4 — CODE 33

# ════════════════════════════════════════════════════════════════════════════════

with tab4:

    st.markdown("### Code 33 — Minervini Fundamental Acceleration")



    # ── Fetch data ────────────────────────────────────────────────────────────

    try:

        c33 = get_code33_data(ticker)

    except Exception:

        c33 = {'eps': [], 'rev': [], 'ni': [], 'sources': {},

               'eps_labels': [], 'rev_labels': [],

               'npm': [], 'npm_labels': [], 'npm_ends': [], 'is_us': True}



    eps_raw = c33.get('eps', [])

    rev_raw = c33.get('rev', [])

    ni_raw  = c33.get('ni',  [])

    sources = c33.get('sources', {})

    is_us   = c33.get('is_us', True)

    sector_excluded      = c33.get('sector_excluded', False)

    excluded_sector_name = c33.get('excluded_sector_name', '')

    is_reit              = c33.get('is_reit', False)

    eps_prior_vals = c33.get('eps_prior_vals', [])

    eps_labels = c33.get('eps_labels', [])

    rev_labels = c33.get('rev_labels', [])

    npm_raw    = c33.get('npm', [])

    npm_labels = c33.get('npm_labels', [])

    npm_ends   = c33.get('npm_ends', [])



    # ── Pre-profit detection ──────────────────────────────────────────────────

    # Only flag as pre-profit if ALL of last 6 EPS quarters are negative.

    # Companies with any positive EPS in last 6Q get evaluated normally.

    is_preprofit = False

    if len(eps_raw) >= 6:

        last6_eps = eps_raw[-6:]

        if all(v is not None and v < 0 for v in last6_eps):

            is_preprofit = True



    # ── Pre-computed YoY rates ────────────────────────────────────────────────

    eps_yoy = c33.get('eps_yoy', [])

    rev_yoy = c33.get('rev_yoy', [])



    # Last 3 valid YoY points + matching labels (chronological)

    eps3, eps_labels3 = _last3_valid_with_labels(eps_yoy, eps_labels)

    rev3, rev_labels3 = _last3_valid_with_labels(rev_yoy, rev_labels)



    # Last 3 margin quarters

    npm3        = npm_raw[-3:]    if len(npm_raw)    >= 3 else []

    npm_labels3 = npm_labels[-3:] if len(npm_labels) >= 3 else []



    eps_status, eps_d1, eps_d2 = _c33_status(eps3)

    rev_status, rev_d1, rev_d2 = _c33_status(rev3)



    # ── Margin status: sequential expansion (margins[-1] > margins[-2] > margins[-3])

    if len(npm3) < 3:

        npm_status = 'insufficient'

        npm_d1 = npm_d2 = None

    else:

        npm_d1 = npm3[1] - npm3[0]   # pp change Q-2 → Q-1

        npm_d2 = npm3[2] - npm3[1]   # pp change Q-1 → Q0

        # NOT APPLICABLE only if ALL 3 margin quarters are negative (fully pre-profit).
        # If Q0 is negative but prior quarters were positive, that is margin collapse = RED.
        if npm3[0] < 0 and npm3[1] < 0 and npm3[2] < 0:

            npm_status = 'not_applicable'

        else:

            margin_expanding = npm_d1 > 0 and npm_d2 > 0

            if margin_expanding:

                npm_status = 'green'

            elif npm_d1 < 0 or npm_d2 < 0:

                npm_status = 'red'

            else:

                npm_status = 'yellow'



    # ── Date-gap guard: null out deltas when consecutive quarters are

    #    not truly adjacent (> 95 days apart) to prevent misleading arrows. ────

    def _gap_checked_deltas(rates3, labels3):

        """Re-derive d1/d2 from rates3 only when labels3 quarters are consecutive."""

        if len(rates3) < 3 or len(labels3) < 3:

            return None, None

        status, d1, d2 = _c33_status(rates3)

        def _label_to_approx_date(lbl):

            try:

                parts = str(lbl).replace('(', '').replace(')', '').strip().split()

                qpart = next((p for p in parts if p.startswith('Q') and p[1:].isdigit()), None)

                yrpart = next((p for p in parts if len(p) == 4 and p.isdigit()), None)

                if qpart and yrpart:

                    import calendar

                    q = int(qpart[1:]); yr = int(yrpart); month = q * 3

                    return datetime(yr, month, calendar.monthrange(yr, month)[1]).date()

            except Exception:

                pass

            return None

        dates = [_label_to_approx_date(l) for l in labels3]

        if dates[0] and dates[1] and abs((dates[1] - dates[0]).days) > 95:

            d1 = None

        if dates[1] and dates[2] and abs((dates[2] - dates[1]).days) > 95:

            d2 = None

        return d1, d2



    eps_d1, eps_d2 = _gap_checked_deltas(eps3, eps_labels3)

    rev_d1, rev_d2 = _gap_checked_deltas(rev3, rev_labels3)

    # FIX 3: margin delta guard uses actual end dates from npm_ends, not labels

    npm_d1_g = npm_d2_g = None

    if len(npm3) == 3 and len(npm_ends) >= 3:

        npm_ends3 = npm_ends[-3:]

        try:

            e0 = datetime.strptime(npm_ends3[0], '%Y-%m-%d').date()

            e1 = datetime.strptime(npm_ends3[1], '%Y-%m-%d').date()

            e2 = datetime.strptime(npm_ends3[2], '%Y-%m-%d').date()

            npm_d1_g = npm_d1 if abs((e1 - e0).days) <= 95 else None

            npm_d2_g = npm_d2 if abs((e2 - e1).days) <= 95 else None

        except Exception:

            pass

    npm_d1 = npm_d1_g

    npm_d2 = npm_d2_g



    # ── Determine overall status ──────────────────────────────────────────────

    if is_preprofit or not is_us or sector_excluded:

        overall = 'not_applicable'

    else:

        statuses = [eps_status, rev_status, npm_status]

        if all(s == 'insufficient' for s in statuses):

            overall = 'insufficient'

        elif 'red' in statuses:

            overall = 'red'

        elif 'yellow' in statuses:

            overall = 'yellow'

        elif all(s == 'green' for s in statuses):

            overall = 'green'

        elif 'insufficient' in statuses:

            overall = 'insufficient'

        else:

            overall = 'green'



    badge_map = {

        'green':          (GREEN,  'ACTIVE',          'EPS & Revenue accelerating · Net Profit Margin expanding'),

        'yellow':         (YELLOW, 'AT RISK',         'Acceleration slowing — watch for deceleration'),

        'red':            (RED,    'BROKEN',          'Deceleration detected — Code 33 is NOT active'),

        'insufficient':   (GRAY,   'INSUFFICIENT',    'Need 7+ quarters of raw data per metric to evaluate'),

        'not_applicable': (GRAY,   'NOT APPLICABLE',  ''),

    }

    bc, bl, bn = badge_map[overall]



    # Custom messages for NOT APPLICABLE

    if overall == 'not_applicable':

        if sector_excluded:

            bn = f"Sector excluded — Code 33 does not apply to {excluded_sector_name or ticker}. Hard exclusions: Utilities, Cyclicals (Steel, Auto, Chemicals, Paper), Airlines. Financials are evaluated normally. REITs run Code 33 with a soft advisory."

        elif is_preprofit:

            bn = f"Code 33 requires accelerating positive earnings. {ticker} is pre-profit."

        elif not is_us:

            bn = f"Code 33 uses SEC EDGAR data. {ticker} is a non-US company — limited data available."



    # Custom message for INSUFFICIENT

    if overall == 'insufficient':

        counts = [len(eps_raw), len(rev_raw), len(npm_raw)]

        mn_count = min(counts)

        bn = f"Need 7+ quarters with EPS, Revenue, and Margin data. Best metric has {max(counts)}Q, worst has {mn_count}Q."



    _status_html = (
        f'<div style="background:{BG};border:2px solid {bc};border-radius:8px;'
        f'padding:14px 22px;margin-bottom:20px;display:flex;align-items:center;gap:20px;">'
        f'<div>'
        f'<div style="color:{GRAY};font-size:10px;font-family:monospace;letter-spacing:2px;">CODE 33 STATUS</div>'
        f'<div style="color:{bc};font-size:26px;font-weight:bold;font-family:\'Courier New\',monospace;margin-top:4px;">{bl}</div>'
        f'</div>'
        f'<div style="color:#CCC;font-size:13px;">{bn}</div>'
        f'</div>'
    )
    st.markdown(_status_html, unsafe_allow_html=True)



    # ── 3 side-by-side cards ──────────────────────────────────────────────────

    def _c33_card(title, rates3, d1, d2, status, unit='%', labels3=None, note=None, distorted_bases=None):

        sc    = {'green': GREEN, 'yellow': YELLOW, 'red': RED, 'insufficient': GRAY, 'not_applicable': GRAY}[status]

        sl    = {'green': 'ACTIVE', 'yellow': 'AT RISK', 'red': 'BROKEN', 'insufficient': 'INSUFFICIENT', 'not_applicable': 'N/A'}[status]

        bg    = {'green': '#0d2818', 'yellow': '#1a1500', 'red': '#2a0d0d', 'insufficient': '#1a1a1a', 'not_applicable': '#1a1a1a'}[status]



        if len(rates3) < 3:

            body = f'<div style="color:{GRAY};padding:12px;text-align:center;">Insufficient data<br><span style="font-size:10px">Need ≥7 raw quarters</span></div>'

        else:

            g1, g2, g3 = rates3[-3], rates3[-2], rates3[-1]

            def _qrow(label, rate, delta=None, is_first=False):

                delta_html = '' if is_first else f'<div style="font-size:11px;margin-bottom:3px">{_delta_badge(delta)}</div>'

                return (f'<div style="padding:8px 0;border-bottom:1px solid #2a2a2a;">'

                        f'{delta_html}'

                        f'<div style="display:flex;justify-content:space-between;align-items:center">'

                        f'<span style="color:{GRAY};font-size:11px;font-family:monospace">{label}</span>'

                        f'<span style="font-size:14px">{_rate_badge(rate)}</span></div></div>')

            db = (distorted_bases or []) or [False, False, False]

            def _db_tag(i): return ' <span style="color:#FF4444;font-size:9px">[Distorted Base]</span>' if (len(db) > i and db[i]) else ''

            l1 = (f'Q-2 ({labels3[0]})' if labels3 and len(labels3) > 0 else 'Q-2 (oldest)') + _db_tag(0)

            l2 = (f'Q-1 ({labels3[1]})' if labels3 and len(labels3) > 1 else 'Q-1')           + _db_tag(1)

            l3 = (f'Q0 ({labels3[2]})'  if labels3 and len(labels3) > 2 else 'Q0 (latest)')   + _db_tag(2)

            body = (_qrow(l1, g1, is_first=True) +

                    _qrow(l2, g2, delta=d1) +

                    _qrow(l3, g3, delta=d2))



        note_html = ''

        if note:

            note_html = f'<div style="color:{YELLOW};font-size:10px;text-align:center;margin-top:6px;font-style:italic">{note}</div>'



        return (f'<div style="background:{bg};border:2px solid {sc};border-radius:8px;padding:14px 16px;height:100%">'

                f'<div style="color:#FFF;font-size:13px;font-weight:bold;margin-bottom:8px">{title}</div>'

                f'{body}{note_html}'

                f'<div style="margin-top:10px;text-align:center;background:{sc}22;border-radius:4px;padding:4px">'

                f'<span style="color:{sc};font-weight:bold;font-size:11px;font-family:monospace">{sl}</span></div>'

                f'</div>')



    card_col1, card_col2, card_col3 = st.columns(3)



    # ── Margin card renderer (different from rate cards — shows absolute %) ───

    def _margin_card(title, margins3, d1, d2, status, labels3=None, note=None):

        sc  = {'green': GREEN, 'yellow': YELLOW, 'red': RED, 'insufficient': GRAY, 'not_applicable': GRAY}[status]

        sl  = {'green': 'ACTIVE', 'yellow': 'AT RISK', 'red': 'BROKEN', 'insufficient': 'INSUFFICIENT', 'not_applicable': 'N/A'}[status]

        bg  = {'green': '#0d2818', 'yellow': '#1a1500', 'red': '#2a0d0d', 'insufficient': '#1a1a1a', 'not_applicable': '#1a1a1a'}[status]



        def _margin_badge(m):

            if m is None: return f'<span style="color:{GRAY}">N/A</span>'

            c = GREEN if m > 0 else (RED if m < 0 else GRAY)

            return f'<span style="color:{c};font-weight:bold;">{m:+.1f}%</span>'



        if len(margins3) < 3:

            body = f'<div style="color:{GRAY};padding:12px;text-align:center;">Insufficient data<br><span style="font-size:10px">Need ≥3 margin quarters</span></div>'

        else:

            def _mrow(label, margin, delta=None, is_first=False):

                delta_html = '' if is_first else f'<div style="font-size:11px;margin-bottom:3px">{_delta_badge(delta)}</div>'

                return (f'<div style="padding:8px 0;border-bottom:1px solid #2a2a2a;">'

                        f'{delta_html}'

                        f'<div style="display:flex;justify-content:space-between;align-items:center">'

                        f'<span style="color:{GRAY};font-size:11px;font-family:monospace">{label}</span>'

                        f'<span style="font-size:14px">{_margin_badge(margin)}</span></div></div>')

            l1 = f'Q-2 ({labels3[0]})' if labels3 and len(labels3) > 0 else 'Q-2 (oldest)'

            l2 = f'Q-1 ({labels3[1]})' if labels3 and len(labels3) > 1 else 'Q-1'

            l3 = f'Q0  ({labels3[2]})' if labels3 and len(labels3) > 2 else 'Q0 (latest)'

            body = (_mrow(l1, margins3[0], is_first=True) +

                    _mrow(l2, margins3[1], delta=d1) +

                    _mrow(l3, margins3[2], delta=d2))



        note_html = ''

        if note:

            note_html = f'<div style="color:{YELLOW};font-size:10px;text-align:center;margin-top:6px;font-style:italic">{note}</div>'



        return (f'<div style="background:{bg};border:2px solid {sc};border-radius:8px;padding:14px 16px;height:100%">'

                f'<div style="color:#FFF;font-size:13px;font-weight:bold;margin-bottom:8px">{title}</div>'

                f'{body}{note_html}'

                f'<div style="margin-top:10px;text-align:center;background:{sc}22;border-radius:4px;padding:4px">'

                f'<span style="color:{sc};font-weight:bold;font-size:11px;font-family:monospace">{sl}</span></div>'

                f'</div>')



    if is_preprofit:

        card_col1.markdown(_c33_card("EPS Growth YoY%", [], None, None, 'not_applicable',

                                     labels3=eps_labels3, note="EPS negative — skipped"), unsafe_allow_html=True)

        card_col2.markdown(_c33_card("Revenue Growth YoY%", rev3, rev_d1, rev_d2,

                                     rev_status if rev_status != 'insufficient' else 'insufficient',

                                     labels3=rev_labels3, note="Revenue only — EPS negative"), unsafe_allow_html=True)

        card_col3.markdown(_margin_card("Net Profit Margin %", npm3, npm_d1, npm_d2,

                                        npm_status, labels3=npm_labels3, note="Pre-profit — margin may be negative"),

                           unsafe_allow_html=True)

    else:

        card_col1.markdown(_c33_card("EPS Growth YoY%",     eps3, eps_d1, eps_d2, eps_status, labels3=eps_labels3, distorted_bases=[v < 0 for v in (eps_prior_vals or [])][-3:] if eps_prior_vals else None), unsafe_allow_html=True)

        card_col2.markdown(_c33_card("Revenue Growth YoY%", rev3, rev_d1, rev_d2, rev_status, labels3=rev_labels3), unsafe_allow_html=True)

        card_col3.markdown(_margin_card("Net Profit Margin %", npm3, npm_d1, npm_d2,

                                        npm_status, labels3=npm_labels3), unsafe_allow_html=True)



    # ── REIT soft warning ─────────────────────────────────────────────────
    if is_reit and not sector_excluded:
        _reit_html = (
            f'<div style="background:#1a1200;border:2px solid {YELLOW};border-radius:8px;'
            f'padding:12px 18px;margin-top:12px;margin-bottom:8px;">'
            f'<span style="color:{YELLOW};font-weight:bold;font-size:13px;">&#9888; REIT Detected — Soft Advisory</span>'
            f'<br><span style="color:#CCC;font-size:12px;">Standard EPS / Revenue / Net Margin metrics may not reflect true '
            f'business performance for Real Estate Investment Trusts. '
            f'Consider using FFO (Funds From Operations) instead of Net Income for evaluation. '
            f'Code 33 signal shown above is indicative only.</span>'
            f'</div>'
        )
        st.markdown(_reit_html, unsafe_allow_html=True)

    # ── Distorted Base warning (Feature 2) ───────────────────────────────────
    _eps_distorted = [v < 0 for v in (eps_prior_vals or [])][-3:] if eps_prior_vals else []
    if any(_eps_distorted):
        _db_html = (
            f'<div style="background:#1a1200;border:2px solid {YELLOW};border-radius:8px;'
            f'padding:12px 18px;margin-top:12px;margin-bottom:8px;">'
            f'<span style="color:{YELLOW};font-weight:bold;font-size:13px;">⚠ Manual Review Required</span>'
            f'<br><span style="color:#CCC;font-size:12px;">One or more quarters contain a distorted EPS base '
            f'(prior-year EPS was negative). Strip one-time items and verify the underlying EPS trend '
            f'before acting on this signal.</span>'
            f'</div>'
        )
        st.markdown(_db_html, unsafe_allow_html=True)

    # ── Debug caption ──────────────────────────────────────────────────────────

    eps_n = len([v for v in eps_raw if v is not None])

    rev_n = len([v for v in rev_raw if v is not None])

    npm_n = len([v for v in npm_raw if v is not None])

    us_tag = 'US' if is_us else 'Non-US'

    preprofit_tag = ' · PRE-PROFIT' if is_preprofit else ''

    st.caption(

        f"Data — EPS: {eps_n}Q ({sources.get('eps','—')}) · "

        f"Revenue: {rev_n}Q ({sources.get('rev','—')}) · "

        f"Net Margin: {npm_n}Q ({sources.get('ni','—')}) · "

        f"{us_tag}{preprofit_tag}"

    )



    # ── Minervini note ────────────────────────────────────────────────────────

    st.markdown(f"""

<div style="background:{BG};border-left:3px solid {YELLOW};border-radius:4px;

            padding:12px 16px;margin-top:12px;font-size:12px;color:#CCC;line-height:1.7">

  <b style="color:{YELLOW}">Rules:</b>

  <span style="color:{GREEN}">GREEN rate</span> = positive &nbsp;|&nbsp;

  <span style="color:{RED}">RED rate</span> = negative &nbsp;|&nbsp;

  <span style="color:{GREEN}">▲ delta</span> = accelerating &nbsp;|&nbsp;

  <span style="color:{RED}">▼ delta</span> = decelerating → any negative Δ = <b style="color:{RED}">BROKEN</b><br>

  <b style="color:{YELLOW}">Minervini:</b> "Dell peaked when EPS growth decelerated from 80%→65%→28%.

  Each number was still high — but the shrinking delta confirmed institutional distribution was underway.

  Code 33 breaks the moment ANY metric decelerates, regardless of the absolute growth level."

</div>""", unsafe_allow_html=True)



    with st.expander("Code 33 Full Rules", expanded=False):

        st.markdown(f"""

**Three metrics must ALL simultaneously hold for 3 consecutive quarters:**



1. **EPS Growth YoY%** — rate must increase quarter-over-quarter (positive delta)

2. **Revenue Growth YoY%** — rate must increase quarter-over-quarter (positive delta)

3. **Net Income Growth YoY%** — rate must increase quarter-over-quarter (positive delta)



**Status:**

- <span style="color:{GREEN}">**ACTIVE**</span> — all 3: both deltas positive AND Δ2 ≥ Δ1

- <span style="color:{YELLOW}">**AT RISK**</span> — all 3 rates positive, but at least one Δ is shrinking (Δ2 < Δ1, both still positive)

- <span style="color:{RED}">**BROKEN**</span> — any metric has any negative delta

- **NOT APPLICABLE** — pre-profit company (all recent EPS negative) or non-US company

- EPS 80% → 65% → 28% = **BROKEN** (Δ=-15pp, Δ=-37pp — both negative)

""", unsafe_allow_html=True)



# ════════════════════════════════════════════════════════════════════════════════

# TAB 5 — NEWS

# ════════════════════════════════════════════════════════════════════════════════

with tab5:

    hdr_col, btn_col = st.columns([3, 1])

    with hdr_col: st.markdown("### News Feed")

    with btn_col:

        if st.button("Refresh", use_container_width=True):

            st.cache_data.clear(); st.rerun()



    try:

        news_items = fetch_stock_news(ticker)

    except Exception:

        news_items = []



    if news_items:

        for item in news_items:

            title = item.get('title',''); src = item.get('source','')

            pub   = item.get('published',''); link = item.get('link','')

            link_html = (f'<a href="{link}" target="_blank" style="color:{GREEN};text-decoration:none">{title}</a>'

                         if link else f'<span style="color:#CCC">{title}</span>')

            st.markdown(

                f'<div style="background:{BG};border:1px solid #222;border-radius:6px;'

                f'padding:10px 14px;margin-bottom:8px">'

                f'<div style="font-size:13px;line-height:1.5;margin-bottom:4px">{link_html}</div>'

                f'<div style="font-size:11px;color:{GRAY};font-family:monospace">{src} · {pub}</div></div>',

                unsafe_allow_html=True)

    else:

        st.info(f"No recent news for {ticker}. Check the ticker or try again later.")



    st.caption(f"Auto-refresh: 5 min cache · Sources: Finnhub + Alpaca · {datetime.now().strftime('%H:%M')}")

