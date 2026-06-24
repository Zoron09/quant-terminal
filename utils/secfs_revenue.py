"""
utils/secfs_revenue.py — Local SEC bulk-dataset (secfsdstools) quarterly Revenue fetcher,
merged with utils/edgar_revenue.py (live edgartools/HTTP) at the quarter level.

get_quarterly_revenue() pulls every quarter secfsdstools (local parquet DB) has for the
ticker, then queries edgartools and uses it ONLY to fill quarters secfsdstools is missing
— secfsdstools wins whenever both sources cover the same period. This handles the case
where the local bulk DB lags live filings by ~1 quarter (SEC only publishes bulk datasets
quarterly) without discarding the (cheap, already-fetched) historical quarters secfsdstools
does have. get_quarterly_revenue_yoy() then applies a 365-day staleness check to the
merged result and returns [] if even the merge can't produce anything recent enough.

PERFORMANCE NOTES:
  1. Avoids secfsdstools' CompanyReportCollector and any collector path that spins up
     its ParallelExecutor — empirically 40-340s per call on this machine regardless of
     how many CIKs are requested (ProcessPoolExecutor spin-up cost on Windows).
  2. Avoids secfsdstools' SingleReportCollector / BaseCollector per filing too — each
     call re-reads the full num.txt.parquet for that filing's quarter (~85MB) from disk,
     and benchmarking showed adsh/tag filter pushdown does NOT make this faster than an
     unfiltered read (the file isn't physically sorted/clustered by adsh, so predicate
     pushdown can't skip row groups) — so per-filing collection costs ~0.3-0.7s
     regardless, and a ticker needing ~14-18 filings costs 15-30s doing it that way.
  3. Instead, reads each quarterly num.txt.parquet ONCE (tag-filtered to just the
     revenue/NI concepts we ever care about, columns pruned), via _load_quarter_tags(),
     and caches it in-process keyed by the quarter's folder path. The sqlite-backed
     CompanyIndexReader (~1s) gives the (adsh, period, fullPath) for each filing without
     touching any parquet data, and fullPath tells us exactly which quarter-cache to
     filter in memory (a sub-millisecond pandas filter on an already-resident
     dataframe). Across a multi-ticker batch (see tools/run_c33_batch.py), the ~14-18
     most recent quarterly files get loaded once each and then reused for every ticker —
     amortizing the one-time ~0.3-0.7s/quarter disk cost across the whole run instead of
     paying it per filing per ticker.
"""

import logging
import os
import threading
from datetime import date, timedelta

import pandas as pd

from secfsdstools.c_index.companyindexreading import CompanyIndexReader

from utils.sec_edgar import get_cik
from utils.edgar_revenue import get_quarterly_revenue as _edgar_get_quarterly_revenue

log = logging.getLogger(__name__)

_REV_TAGS = [
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'RevenueFromContractWithCustomerIncludingAssessedTax',
    'Revenues',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet',
    'RevenueFromContractWithCustomer',
]

_NI_TAGS = [
    'NetIncomeLoss',
    'NetIncome',
    'ProfitLoss',
    'NetIncomeLossAvailableToCommonStockholdersBasic',
]

# Combined so a single cached quarter-read serves both secfs_revenue and
# secfs_net_margin — see _load_quarter_tags().
_ALL_TAGS = _REV_TAGS + _NI_TAGS

_NUM_COLUMNS = ['adsh', 'tag', 'ddate', 'qtrs', 'segments', 'coreg', 'value']

# ── Shared, process-wide quarter cache ──────────────────────────────────────
# keyed by the quarter folder's fullPath (e.g. ".../quarter/2026q1.zip");
# reused by utils/secfs_net_margin.py so revenue + NI share the same reads.
_TAG_CACHE: dict[str, pd.DataFrame] = {}
_TAG_CACHE_LOCK = threading.Lock()


def _load_quarter_tags(full_path: str) -> pd.DataFrame:
    """
    Tag-filtered, column-pruned num.txt for one quarterly zip folder, loaded
    from disk once and cached for the lifetime of the process. Thread-safe.
    """
    cached = _TAG_CACHE.get(full_path)
    if cached is not None:
        return cached
    with _TAG_CACHE_LOCK:
        cached = _TAG_CACHE.get(full_path)
        if cached is not None:
            return cached
        try:
            df = pd.read_parquet(
                os.path.join(full_path, 'num.txt.parquet'),
                columns=_NUM_COLUMNS,
                filters=[('tag', 'in', _ALL_TAGS), ('uom', '==', 'USD')],
            )
            df['coreg'] = df['coreg'].fillna('')
            df['segments'] = df['segments'].fillna('')
        except Exception as exc:
            log.warning("secfs_revenue: _load_quarter_tags('%s') failed: %s", full_path, exc)
            df = pd.DataFrame(columns=_NUM_COLUMNS)
        _TAG_CACHE[full_path] = df
        return df


# ── Private helpers ───────────────────────────────────────────────────────────

def _to_m(val: float) -> float:
    """
    Convert raw USD value to millions, rounded to 1 decimal.

    Always divides — unlike edgar_revenue.py's same-named helper, which skips
    the division below $1M. That heuristic assumes "small raw value means
    it's already in millions," which is wrong: a small-cap's actual quarterly
    NI/revenue can legitimately be sub-$1M in raw dollars (confirmed: ASYS NI
    of $312,000 was left as 312000.0 instead of 0.3, producing a >500,000%
    net margin). XBRL num.txt values are always raw USD regardless of
    company size, so there's no case where skipping the division is correct.
    """
    return round(val / 1_000_000, 1)


def _is_implausible(q4: float, q1: float, q2: float, q3: float) -> bool:
    """Same guard as utils/edgar_revenue.py: negative Q4, or Q4 > 4x peer-quarter avg."""
    if q4 <= 0:
        return True
    avg = (q1 + q2 + q3) / 3
    if avg > 0 and q4 > avg * 4.0:
        return True
    return False


def _int_to_date(ddate: int) -> date:
    s = str(int(ddate))
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _own_period_value(quarter_df: pd.DataFrame, adsh: str, own_period: int,
                       tags: list, qtrs: int) -> float | None:
    """
    Best consolidated (no segment/coreg dimension) value for the given tag
    priority list, pinned to this filing's own adsh + period end + qtrs
    duration — mirrors the BUG2 own-period pin in edgar_revenue.py, filtering
    an already-cached in-memory quarter dataframe instead of hitting disk.
    """
    try:
        pool = quarter_df[
            (quarter_df['adsh'] == adsh)
            & (quarter_df['ddate'] == own_period)
            & (quarter_df['qtrs'] == qtrs)
            & (quarter_df['segments'] == '')
            & (quarter_df['coreg'] == '')
        ]
    except Exception as exc:
        log.warning("secfs_revenue: _own_period_value filter failed: %s", exc)
        return None
    for tag in tags:
        match = pool[pool['tag'] == tag]
        if not match.empty:
            try:
                return float(match.iloc[0]['value'])
            except Exception:
                continue
    return None


def latest_filing_period(cik: int) -> date | None:
    """
    Cheap freshness proxy: most recent 10-Q OR 10-K period-end for cik via the
    sqlite-backed CompanyIndexReader only (~1s, no filing collection).

    The freshest quarter we can ever extract comes directly from the latest
    filed 10-Q (see _quarterly_revenue_secfs — 10-Qs are emitted standalone,
    not gated on a closing 10-K), so this checks both forms, not just 10-K.

    Returns None (never raises) on any failure or if no filing is on file.
    """
    try:
        reader = CompanyIndexReader.get_company_index_reader(cik=cik)
        reports_df = reader.get_all_company_reports_df(forms=['10-Q', '10-K'])
    except Exception as exc:
        log.warning("secfs_revenue: latest_filing_period cik=%s failed: %s", cik, exc)
        return None
    if reports_df is None or reports_df.empty:
        return None
    try:
        most_recent = int(reports_df['period'].max())
        return _int_to_date(most_recent)
    except Exception:
        return None


def _quarterly_revenue_secfs(cik: int, n_quarters: int) -> list[dict]:
    """
    Up to n_quarters quarters of consolidated revenue for cik, newest first,
    sourced from the local secfsdstools parquet DB.

    Each 10-Q's own-period single-quarter value is emitted directly and
    unconditionally — it does NOT wait for that fiscal year to close. Q4 has
    no standalone 10-Q (SEC filers never report it directly), so it is the
    only quarter still derived from the annual 10-K minus the matching
    Q1+Q2+Q3 (same arithmetic as utils/edgar_revenue.py's BUG4 guard).

    Returns [] (never raises) on any failure or if local data is unavailable.
    """
    try:
        reader = CompanyIndexReader.get_company_index_reader(cik=cik)
        reports_df = reader.get_all_company_reports_df(forms=['10-Q', '10-K'])
    except Exception as exc:
        log.warning("secfs_revenue: CompanyIndexReader cik=%s failed: %s", cik, exc)
        return []
    if reports_df is None or reports_df.empty:
        return []

    n_10q = min(n_quarters + 5, 16)
    n_fy = max((n_quarters // 4) + 2, 4)

    q_reports = reports_df[reports_df['form'] == '10-Q'].sort_values('period', ascending=False).head(n_10q)
    fy_reports = reports_df[reports_df['form'] == '10-K'].sort_values('period', ascending=False).head(n_fy)

    # ── Single-quarter pool from 10-Qs, pinned to each filing's own period ────
    q_pool: dict[int, float] = {}
    for _, rep in q_reports.iterrows():
        adsh, own_period = rep['adsh'], int(rep['period'])
        qdf = _load_quarter_tags(rep['fullPath'])
        val = _own_period_value(qdf, adsh, own_period, _REV_TAGS, qtrs=1)
        if val is not None:
            q_pool[own_period] = val
        else:
            log.warning("secfs_revenue: 10-Q adsh=%s own_period=%s no revenue match", adsh, own_period)

    # ── Emit every 10-Q quarter directly — no fiscal-year-closure gate ─────────
    results: list[dict] = []
    seen: set = set()
    for own_period, rev in q_pool.items():
        period = _int_to_date(own_period)
        seen.add(period)
        results.append({
            'ticker': None, 'period_end': period, 'fiscal_quarter': None,
            'revenue_m': _to_m(rev), 'source': '10-Q',
        })

    # ── Annual values from 10-Ks, pinned to each filing's own period ──────────
    annual_list: list[tuple[int, float]] = []
    for _, rep in fy_reports.iterrows():
        adsh, own_period = rep['adsh'], int(rep['period'])
        qdf = _load_quarter_tags(rep['fullPath'])
        val = _own_period_value(qdf, adsh, own_period, _REV_TAGS, qtrs=4)
        if val is not None:
            annual_list.append((own_period, val))
    annual_list.sort(key=lambda x: x[0], reverse=True)

    # ── Derive Q4 per FY — the only quarter that needs the closing 10-K ───────
    for idx, (fye_int, annual_rev) in enumerate(annual_list):
        try:
            fye = _int_to_date(fye_int)
        except Exception:
            continue
        if fye in seen:
            continue

        if idx + 1 < len(annual_list):
            try:
                prev_fye = _int_to_date(annual_list[idx + 1][0])
            except Exception:
                prev_fye = fye - timedelta(days=366)
        else:
            prev_fye = fye - timedelta(days=366)

        fy_qs = sorted(
            [(_int_to_date(p), v) for p, v in q_pool.items()
             if prev_fye < _int_to_date(p) < fye],
            key=lambda x: x[0],
        )

        if len(fy_qs) < 3:
            continue

        q1_rev, q2_rev, q3_rev = fy_qs[0][1], fy_qs[1][1], fy_qs[2][1]
        q4_rev = round(annual_rev - q1_rev - q2_rev - q3_rev, 1)

        if _is_implausible(q4_rev, q1_rev, q2_rev, q3_rev):
            continue

        seen.add(fye)
        results.append({
            'ticker': None, 'period_end': fye, 'fiscal_quarter': 'Q4',
            'revenue_m': _to_m(q4_rev), 'source': 'derived_q4',
        })

    results.sort(key=lambda r: r['period_end'], reverse=True)
    return results[:n_quarters]


# ── Public API ────────────────────────────────────────────────────────────────

def get_quarterly_revenue(ticker: str, n_quarters: int = 8) -> list[dict]:
    """
    Merged Revenue series for ticker: secfsdstools (local parquet DB) pulls
    every quarter it has; edgartools (live HTTP) is then queried and used
    ONLY to fill quarters secfsdstools is missing — secfsdstools wins on any
    period both sources cover. Same return shape as
    utils/edgar_revenue.get_quarterly_revenue() (list of dicts, newest first,
    'revenue_m' in USD millions), with 'source' prefixed by which side
    supplied that quarter (e.g. 'secfsdstools:10-Q', 'edgartools:derived_q4').

    Returns [] (never raises) if the ticker has no local CIK match, or if the
    merged result has fewer than 3 quarters total.
    """
    try:
        cik = get_cik(ticker)
        if not cik:
            return []
        cik_int = int(cik)

        secfs_results = _quarterly_revenue_secfs(cik_int, n_quarters)
        merged: dict[date, dict] = {}
        for r in secfs_results:
            period = r['period_end']
            merged[period] = {**r, 'ticker': ticker, 'source': f"secfsdstools:{r['source']}"}
            log.info("secfs_revenue: %s period=%s from secfsdstools (%s)", ticker, period, r['source'])

        # secfsdstools already returned at least as many quarters as asked
        # for — skip the slow live edgartools call entirely. edgartools is
        # only worth its latency when secfsdstools has a real gap to fill.
        if len(merged) >= n_quarters:
            log.info("secfs_revenue: %s has %d/%d secfsdstools quarters — skipping edgartools", ticker, len(merged), n_quarters)
        else:
            try:
                edgar_results = _edgar_get_quarterly_revenue(ticker, n_quarters=n_quarters)
            except Exception as exc:
                log.warning("secfs_revenue: edgartools fetch failed for %s: %s", ticker, exc)
                edgar_results = []

            # Same fiscal quarter can carry slightly different period-end
            # dates between sources (e.g. secfsdstools' calendar-quarter-end
            # vs edgartools' filer-reported fiscal date, off by a few days) —
            # match by proximity, not exact date equality, or every
            # edgartools quarter looks "missing" and gets added as a
            # near-duplicate.
            covered = sorted(merged.keys())
            for r in edgar_results:
                period = r['period_end']
                if any(abs((period - sp).days) <= 45 for sp in covered):
                    continue  # secfsdstools already has this quarter — it wins
                merged[period] = {**r, 'ticker': ticker, 'source': f"edgartools:{r['source']}"}
                covered.append(period)
                log.info("secfs_revenue: %s period=%s filled from edgartools (%s)", ticker, period, r['source'])

        if len(merged) < 3:
            return []

        results = sorted(merged.values(), key=lambda r: r['period_end'], reverse=True)
        return results[:n_quarters]
    except Exception as exc:
        log.warning("secfs_revenue: get_quarterly_revenue('%s') failed: %s", ticker, exc)
        return []


def get_quarterly_revenue_yoy(ticker: str, n_quarters: int = 4) -> list[float]:
    """
    Last n_quarters (default 4) of Revenue YoY growth % for ticker, ascending
    (most recent last), sourced from the merged secfsdstools+edgartools series
    (see get_quarterly_revenue()).

    Returns [] (never raises) when:
      - fewer than 3 quarters of YoY can be computed (too little history from
        either source)
      - the most recent quarter in the merged series is still older than 365
        days (neither source has anything fresh)
      - any exception occurs
    """
    try:
        raw = get_quarterly_revenue(ticker, n_quarters=n_quarters + 5)
        if not raw:
            return []

        most_recent = max(r['period_end'] for r in raw)
        if (date.today() - most_recent).days > 365:
            return []

        by_period = {r['period_end']: r['revenue_m'] for r in raw}
        ordered = sorted(by_period.keys())  # ascending

        yoy: list[float] = []
        for period in ordered:
            curr = by_period[period]
            prior_period = None
            best_diff = 46
            target = period - timedelta(days=365)
            for cand in by_period:
                if cand == period:
                    continue
                diff = abs((cand - target).days)
                if diff < best_diff:
                    best_diff = diff
                    prior_period = cand
            if prior_period is None:
                continue
            prior = by_period[prior_period]
            if not prior:
                continue
            yoy.append(round((curr - prior) / abs(prior) * 100, 2))

        if len(yoy) < 3:
            return []

        return yoy[-n_quarters:]
    except Exception as exc:
        log.warning("secfs_revenue: get_quarterly_revenue_yoy('%s') failed: %s", ticker, exc)
        return []
