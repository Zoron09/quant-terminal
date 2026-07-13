import os
import sys
import logging
import calendar
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Load env vars from root .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

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

CACHE_VERSION = 'v30'

# ── Shared cutoff constants ───────────────────────────────────────────────────
RECENCY_CUTOFF_DAYS = 548   # ~18 months — max staleness for "fresh enough" data

# ── Sector / industry exclusion rules (Minervini SEPA methodology) ───────────
#   Hard exclusion  → NOT APPLICABLE (Utilities, Cyclicals, Airlines)
#   Soft warning    → runs Code 33 but shows REIT advisory
#   No exclusion    → Financials removed per Minervini (can be superperformance leaders)
EXCL_SECTORS = {'Utilities'}
EXCL_INDUSTRY_KEYWORDS = [
    'steel', 'aluminum', 'auto manufacturer', 'automobile',
    'paper', 'packaging', 'chemical', 'fertilizer',
    'airline', 'air freight', 'airports',
]
REIT_KEYWORDS = ['reit', 'real estate investment trust']

# ── Small numeric helpers ─────────────────────────────────────────────────────
def _nan(v):
    if v is None: return True
    try: return isinstance(v, float) and np.isnan(v)
    except Exception: return False

def _sf(v, default=None):
    if _nan(v): return default
    try: return float(v)
    except Exception: return default

def _get_fq_fy(dt, fy_end_m=12) -> str:
    """Correct fiscal quarter/year label from fy_end_m, computed directly —
    never inferred from which calendar month dt happens to land near (the old
    version's `dt.month in (3,6,9,12)` shortcut mislabeled any non-Dec fiscal
    year whose quarter-ends still land on calendar month-ends, e.g. CMP's
    Sept FYE, and any 52/53-week fiscal calendar, e.g. NVDA's Jan FYE).
    Verified by hand against Dec-FYE, CMP (Sept), and NVDA (Jan) before use."""
    try:
        offset = (fy_end_m - dt.month) % 12
        quarter = 4 - offset // 3
        fy_year = dt.year + (1 if dt.month > fy_end_m else 0)
        return f"Q{quarter} {fy_year}"
    except Exception:
        return ""

def _yf_to_m(val: float) -> float:
    """Same conversion discipline as the Commit-1-fixed _to_m() in
    secfs_revenue.py/edgar_revenue.py — divide unconditionally, round to 4
    decimals, not 1. yfinance's quarterly_income_stmt already returns raw
    USD (same as the other two sources), so there's no skip-bug to inherit
    here, but routing through this keeps precision handling identical
    across all three revenue sources rather than giving yfinance silently
    different (uncapped) precision."""
    return round(val / 1_000_000, 4)

def _yfinance_revenue_pairs(ticker: str) -> list:
    """Raw (date, revenue_usd) pairs from yfinance's quarterly income
    statement — third-leg fallback only, called when secfsdstools and
    edgartools both still have a gap. Fill-only: never overrides an
    existing value, only used by _fill_target_quarters for target dates
    neither of the first two sources covered. Revenue only — no NI/margin
    equivalent (mixing yfinance NI into margin calculations would mix
    accounting bases and complicate Macrotrends cross-verification)."""
    import yfinance as yf
    pairs = []
    try:
        df = yf.Ticker(ticker.upper()).quarterly_income_stmt
        if df is None or df.empty:
            return pairs
        row_name = next((f for f in ('Total Revenue', 'TotalRevenue') if f in df.index), None)
        if row_name is None:
            return pairs
        for col in df.columns:
            v = df.loc[row_name, col]
            if _nan(v):
                continue
            try:
                d = col.date() if hasattr(col, 'date') else date.fromisoformat(str(col)[:10])
                raw = _yf_to_m(float(v)) * 1_000_000
                pairs.append((d, raw))
            except Exception:
                continue
    except Exception:
        log.warning("code33_engine: %s yfinance revenue fallback failed", ticker)
    return pairs

_MARGIN_PLAUSIBLE_BOUND_PCT = 1000.0

def _is_plausible_margin(pct, ticker: str, period_end) -> bool:
    """Tripwire, not primarily a nuller: catches a wrong margin value (e.g.
    a scaling/extraction bug like Commit 1's TRT case, -230,303% instead of
    -0.23%) before it reaches output, rather than asserting any specific
    quarter's margin is definitely wrong. Deliberately loose (+-1000%) —
    real one-time gains or tax benefits can legitimately push margin past
    +-200%, so this only rejects values outside any screener-meaningful
    range, not merely unusual-but-real quarters.

    Called at ingestion (where code33_engine.py pulls net_margin_pct from
    secfsdstools/edgartools into its own merge pipeline), not at the
    upstream computation point in secfs_net_margin.py/edgar_net_margin.py —
    so only ticker/period/computed-margin are available to log here, not
    the raw NI/revenue that produced it (those aren't returned by either
    upstream function). Returns False so the caller excludes the pair
    entirely rather than including a null placeholder — that leaves the
    date open for the other source (secfsdstools vs edgartools) to fill
    instead, and only ends up null if neither has a plausible value."""
    if pct is None:
        return True
    if abs(pct) > _MARGIN_PLAUSIBLE_BOUND_PCT:
        log.warning(
            "code33_engine: %s period=%s implausible margin %.2f%% rejected "
            "(outside +-%.0f%%) — excluded, not passed through",
            ticker, period_end, pct, _MARGIN_PLAUSIBLE_BOUND_PCT
        )
        return False
    return True

def _date_first_yoy(primary_vals, primary_ends, edgar_vals, edgar_ends, primary_fy=None, primary_fp=None, edgar_fy=None, edgar_fp=None, fy_end_m=12, src_primary='primary', src_fallback='EDGAR', append_none=False):
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

    primary_pool = _make_pool(primary_vals, primary_ends, primary_fy, primary_fp, src_primary)
    edgar_pool   = _make_pool(edgar_vals, edgar_ends, edgar_fy, edgar_fp, src_fallback)

    f_yoy = _yoy_for_src(primary_pool, fallback_pool=edgar_pool)
    e_yoy = _yoy_for_src(edgar_pool, fallback_pool=primary_pool)

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

def _insufficient_result(ticker: str, reason: str = 'unhandled error') -> dict:
    """Safe fallback dict, same shape as get_code33_data()'s normal return.
    Used whenever a ticker can't be processed so callers never see an exception."""
    log.warning("code33_engine: %s returning INSUFFICIENT (%s)", ticker, reason)
    return {
        'eps': [], 'rev': [], 'ni': [],
        'eps_end_dates': [], 'rev_end_dates': [], 'ni_end_dates': [],
        'eps_yoy': [], 'rev_yoy': [],
        'eps_labels': [], 'rev_labels': [],
        'npm': [], 'npm_labels': [], 'npm_ends': [],
        'sources': {'rev': 'insufficient', 'ni': 'insufficient', 'eps': 'insufficient'},
        'is_us': True,
        'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': 'insufficient',
        'eps_prior_vals': [], 'eps_sources': [],
    }


def get_code33_data(ticker: str, cache_v: str = CACHE_VERSION, n_quarters: int = 8) -> dict:
    """Fetch Revenue + Net Margin for Code 33 analysis. EPS is out of scope (not fetched).

    Revenue + Net Margin: secfsdstools primary, edgartools fallback. No other sources.
    Need minimum 8 raw quarters per metric to compute 4 YoY rates (3 acceleration deltas).

    n_quarters: how many of the most recent fiscal quarters to target (default 8, the
    Code 33 signal's own requirement). Callers needing a longer display/lookback window
    (e.g. api/server.py's /api/financials endpoint, which needs a buffer for its own
    index-based YoY calc) can pass a larger value — purely additive, existing callers
    are unaffected by the default.

    Never raises — any unhandled error falls back to an INSUFFICIENT result so callers
    (screener batch runs, server endpoints, pages) never crash on a single bad ticker."""
    try:
        return _get_code33_data_inner(ticker, cache_v, n_quarters)
    except Exception:
        log.exception("code33_engine: %s unhandled error in get_code33_data", ticker)
        return _insufficient_result(ticker, 'unhandled exception')


def _get_code33_data_inner(ticker: str, cache_v: str = CACHE_VERSION, n_quarters: int = 8) -> dict:
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

        if sector in EXCL_SECTORS:

            sector_excluded = True

            excluded_sector_name = sector

        else:

            ind_lower = industry.lower()

            for kw in EXCL_INDUSTRY_KEYWORDS:

                if kw in ind_lower:

                    sector_excluded = True

                    excluded_sector_name = industry

                    break

        # Detect REIT for soft warning (sector='Real Estate' or industry keyword)
        is_reit = (
            sector == 'Real Estate' or
            any(kw in industry.lower() for kw in REIT_KEYWORDS)
        )

    except Exception:

        is_us = True

        is_reit = False



    sources = {}







    def _is_recent(end_dates, max_days=RECENCY_CUTOFF_DAYS):

        """Reject data if most recent date is older than max_days (~18 months)."""

        if not end_dates:

            return False

        try:

            most_recent = max(datetime.strptime(d, '%Y-%m-%d').date() for d in end_dates)

            return (datetime.utcnow().date() - most_recent).days <= max_days

        except Exception:

            return False

    def _target_quarter_ends(fy_end_m, today, n=8, filing_lag_days=45):
        """The n most recent fiscal quarter-end dates that should already be
        filed as of `today`, given this ticker's fiscal-year-end month.
        Pure date math — does NOT use _get_fq_fy, whose Q-number labeling is
        known-wrong for non-Dec fiscal years whose quarter-ends still land on
        calendar month-ends (e.g. Sept FYE). Descending, most recent first."""
        q_months = sorted({((fy_end_m - 1 - 3 * k) % 12) + 1 for k in range(4)})

        def _month_end(y, m):
            return date(y, m, calendar.monthrange(y, m)[1])

        results = []
        y, m = today.year, today.month
        while len(results) < n:
            if m in q_months:
                cand = _month_end(y, m)
                if (today - cand).days >= filing_lag_days:
                    results.append(cand)
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        return results

    def _fill_target_quarters(targets, primary_pairs, secondary_pairs, tertiary_pairs=None, tolerance_days=45):
        """For each target date: primary_pairs (secfsdstools) wins if it has a
        match within tolerance_days; else secondary_pairs (edgartools) fills
        it; else tertiary_pairs (currently: yfinance, revenue only) fills it
        if given; else the slot is None and its date is reported as missing.
        primary_pairs/secondary_pairs/tertiary_pairs are lists of (date, value).
        Target dates drive matching only — the displayed end date is the real
        filed date from whichever source matched, never the synthetic target
        (a real filing can land ~26-45 days from its target, and for a fiscal
        year-end quarter that can even cross a calendar-year boundary).
        Returns (vals, ends, missing) — vals/ends len == len(targets),
        ascending (oldest first); missing = ISO date strings still unfilled."""
        def _find(target, pairs):
            best, best_diff = None, tolerance_days + 1
            for dt, v in pairs:
                diff = abs((dt - target).days)
                if diff <= tolerance_days and diff < best_diff:
                    best, best_diff = (dt, v), diff
            return best

        rows = []
        for target in sorted(targets):
            match = _find(target, primary_pairs)
            if match is None:
                match = _find(target, secondary_pairs)
            if match is None and tertiary_pairs:
                match = _find(target, tertiary_pairs)
            if match is None:
                rows.append((target, None))
            else:
                real_dt, v = match
                rows.append((real_dt, v))

        vals = [v for _, v in rows]
        ends = [t.isoformat() for t, _ in rows]
        missing = [t.isoformat() for t, v in rows if v is None]
        return vals, ends, missing

    _targets = _target_quarter_ends(fy_end_month, datetime.utcnow().date(), n=n_quarters)

    # ── Revenue: check secfsdstools against the named target quarters first;
    # only call edgartools if secfsdstools actually has a gap to fill ────────
    secfs_rev_pairs = []
    if _HAS_SECFS_REV:
        try:
            _secfs_rev = get_quarterly_revenue_secfs(ticker, n_quarters=16)
            for r in _secfs_rev:
                secfs_rev_pairs.append((r['period_end'], r['revenue_m'] * 1_000_000))  # millions -> raw USD
        except Exception:
            log.warning("code33_engine: %s secfsdstools revenue failed", ticker)
            secfs_rev_pairs = []

    _rev_vals_precheck, _, _rev_missing_precheck = _fill_target_quarters(_targets, secfs_rev_pairs, [])

    edgartools_rev_pairs = []
    if _HAS_EDGARTOOLS_REV and _rev_missing_precheck:
        try:
            _et_rev = get_quarterly_revenue(ticker, n_quarters=16)
            for r in _et_rev:
                edgartools_rev_pairs.append((r['period_end'], r['revenue_m'] * 1_000_000))
        except Exception:
            log.warning("code33_engine: %s edgartools revenue failed", ticker)
            edgartools_rev_pairs = []

    _rev_vals_after_edgar, _, _rev_missing_after_edgar = _fill_target_quarters(
        _targets, secfs_rev_pairs, edgartools_rev_pairs
    )
    _rev_edgar_contributed = bool(edgartools_rev_pairs) and len(_rev_missing_after_edgar) < len(_rev_missing_precheck)

    # ── Revenue, third leg: yfinance, fill-only — only called when
    # secfsdstools and edgartools both still leave a gap. Never overrides a
    # value either already provided. Revenue only, no NI/margin equivalent.
    yfinance_rev_pairs = []
    if _rev_missing_after_edgar:
        yfinance_rev_pairs = _yfinance_revenue_pairs(ticker)

    rev_target_vals, rev_target_ends, rev_missing = _fill_target_quarters(
        _targets, secfs_rev_pairs, edgartools_rev_pairs, yfinance_rev_pairs
    )
    _rev_yfinance_contributed = bool(yfinance_rev_pairs) and len(rev_missing) < len(_rev_missing_after_edgar)
    _rev_yfinance_filled = sorted(set(_rev_missing_after_edgar) - set(rev_missing))

    rev_yoy_final, rev_labels_final, _, _, _ = _date_first_yoy(
        rev_target_vals, rev_target_ends, [], [], None, None, None, None,
        fy_end_m=fy_end_month, append_none=True
    )

    _rev_ok = (
        len([x for x in rev_yoy_final if x is not None]) >= 3
        and _is_recent([e for e, v in zip(rev_target_ends, rev_target_vals) if v is not None])
    )

    if _rev_ok:
        rev_raw_final, rev_raw_ends_final = rev_target_vals, rev_target_ends
        if not secfs_rev_pairs:
            sources['rev'] = 'EDGAR-edgartools'
        elif _rev_edgar_contributed:
            sources['rev'] = 'secfsdstools+EDGAR-edgartools'
        else:
            sources['rev'] = 'secfsdstools'
        if _rev_yfinance_contributed:
            sources['rev'] += '+yfinance'
        # Provenance: which specific target quarters yfinance filled (empty
        # list for the vast majority of tickers, which never reach this leg).
        sources['rev_yfinance_filled'] = _rev_yfinance_filled
    else:
        rev_yoy_final, rev_labels_final = [], []
        rev_raw_final, rev_raw_ends_final = [], []
        sources['rev'] = 'insufficient'

    sources['rev_missing'] = rev_missing
    log.info("code33_engine: %s rev source = %s, missing = %s", ticker, sources['rev'], rev_missing)

    # ── Net Profit Margin: same targeted-gap approach, fully independent of
    # revenue's gaps — a quarter can be missing from one and not the other ───
    secfs_npm_pairs = []
    if _HAS_SECFS_MARGIN:
        try:
            _secfs_npm = get_quarterly_net_margin_secfs(ticker, n_quarters=16)
            for r in _secfs_npm:
                if _is_plausible_margin(r['net_margin_pct'], ticker, r['period_end']):
                    secfs_npm_pairs.append((r['period_end'], r['net_margin_pct']))
        except Exception:
            log.warning("code33_engine: %s secfsdstools net margin failed", ticker)
            secfs_npm_pairs = []

    _npm_vals_precheck, _, _npm_missing_precheck = _fill_target_quarters(_targets, secfs_npm_pairs, [])

    edgartools_npm_pairs = []
    if _HAS_EDGARTOOLS_MARGIN and _npm_missing_precheck:
        try:
            _et_npm = get_quarterly_net_margin(ticker, n_quarters=16)
            for r in _et_npm:
                if _is_plausible_margin(r['net_margin_pct'], ticker, r['period_end']):
                    edgartools_npm_pairs.append((r['period_end'], r['net_margin_pct']))
        except Exception:
            log.warning("code33_engine: %s edgartools net margin failed", ticker)
            edgartools_npm_pairs = []

    npm_target_vals, npm_target_ends, npm_missing = _fill_target_quarters(
        _targets, secfs_npm_pairs, edgartools_npm_pairs
    )
    _npm_edgar_contributed = bool(edgartools_npm_pairs) and len(npm_missing) < len(_npm_missing_precheck)

    _npm_ok = (
        len([x for x in npm_target_vals if x is not None]) >= 3
        and _is_recent([e for e, v in zip(npm_target_ends, npm_target_vals) if v is not None])
    )

    if _npm_ok:
        npm_vals = npm_target_vals
        npm_ends_final = npm_target_ends
        npm_labels_final = [_get_fq_fy(datetime.strptime(e, '%Y-%m-%d').date(), fy_end_month) for e in npm_target_ends]
        if not secfs_npm_pairs:
            sources['ni'] = 'EDGAR-edgartools'
        elif _npm_edgar_contributed:
            sources['ni'] = 'secfsdstools+EDGAR-edgartools'
        else:
            sources['ni'] = 'secfsdstools'
    else:
        npm_vals, npm_labels_final, npm_ends_final = [], [], []
        sources['ni'] = 'insufficient'

    sources['ni_missing'] = npm_missing
    log.info("code33_engine: %s ni source = %s, missing = %s", ticker, sources['ni'], npm_missing)

    # Neither remaining source exposes absolute net-income $ (secfsdstools /
    # edgartools only expose the margin ratio) — raw 'ni' is intentionally empty.
    ni_raw_final, ni_raw_ends_final = [], []

    # EPS is out of scope — not fetched.
    eps_raw_final, eps_raw_ends_final = [], []
    eps_yoy_final, eps_labels_final = [], []
    eps_prior_vals, eps_sources = [], []
    sources['eps'] = 'disabled'

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
        'eps_prior_vals': eps_prior_vals,
        'eps_sources': eps_sources,
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