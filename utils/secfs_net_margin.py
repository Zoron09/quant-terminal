"""
utils/secfs_net_margin.py — Local SEC bulk-dataset (secfsdstools) quarterly Net
Profit Margin fetcher.

Primary source ahead of utils/edgar_net_margin.py (live edgartools/HTTP) in the
Code33 fallback chain (see utils/code33_engine.py). Same architecture and
performance notes as utils/secfs_revenue.py — reuses its shared, process-wide
quarter cache (_load_quarter_tags) so revenue and NI for the same filing are
read from the same already-resident in-memory dataframe, never re-touching disk.

Net Profit Margin (NI / Revenue x 100) is a level, not a YoY rate — Code33 tracks
whether the margin itself is expanding quarter over quarter (see CLAUDE.md SS8),
matching the convention already used by utils/edgar_net_margin.get_quarterly_net_margin().
"""

import logging
from datetime import date, timedelta

from secfsdstools.c_index.companyindexreading import CompanyIndexReader

from utils.sec_edgar import get_cik
from utils.secfs_revenue import (
    _NI_TAGS,
    _int_to_date,
    _load_quarter_tags,
    _own_period_value,
    get_quarterly_revenue,
    latest_filing_period,
)

log = logging.getLogger(__name__)


# ── Private helpers ───────────────────────────────────────────────────────────

def _to_m(val: float) -> float:
    """Convert raw USD value to millions, rounded to 1 decimal. See
    secfs_revenue._to_m() docstring — always divides, no small-value skip."""
    return round(val / 1_000_000, 1)


def _is_implausible_ni(q4: float, annual: float) -> bool:
    """Same guard as utils/edgar_net_margin.py BUG5: only flags when |Annual| >= $100M."""
    if abs(annual) >= 100 and abs(q4) > abs(annual) * 10:
        return True
    return False


def _quarterly_ni_secfs(cik: int, n_quarters: int) -> list[dict]:
    """
    Up to n_quarters quarters of consolidated Net Income for cik, newest first.

    Each 10-Q's own-period single-quarter value is emitted directly and
    unconditionally — it does NOT wait for that fiscal year to close. Q4 has
    no standalone 10-Q, so it is the only quarter still derived from the
    annual 10-K minus the matching Q1+Q2+Q3 (same architecture as
    secfs_revenue._quarterly_revenue_secfs()).
    """
    try:
        reader = CompanyIndexReader.get_company_index_reader(cik=cik)
        reports_df = reader.get_all_company_reports_df(forms=['10-Q', '10-K'])
    except Exception as exc:
        log.warning("secfs_net_margin: CompanyIndexReader cik=%s failed: %s", cik, exc)
        return []
    if reports_df is None or reports_df.empty:
        return []

    n_10q = min(n_quarters + 5, 16)
    n_fy = max((n_quarters // 4) + 2, 4)

    q_reports = reports_df[reports_df['form'] == '10-Q'].sort_values('period', ascending=False).head(n_10q)
    fy_reports = reports_df[reports_df['form'] == '10-K'].sort_values('period', ascending=False).head(n_fy)

    q_pool: dict[int, float] = {}
    for _, rep in q_reports.iterrows():
        adsh, own_period = rep['adsh'], int(rep['period'])
        qdf = _load_quarter_tags(rep['fullPath'])
        val = _own_period_value(qdf, adsh, own_period, _NI_TAGS, qtrs=1)
        if val is not None:
            q_pool[own_period] = val

    # ── Emit every 10-Q quarter directly — no fiscal-year-closure gate ─────────
    results: list[dict] = []
    seen: set = set()
    for own_period, ni in q_pool.items():
        period = _int_to_date(own_period)
        seen.add(period)
        results.append({'period_end': period, 'net_income_m': _to_m(ni), 'source': '10-Q'})

    annual_list: list[tuple[int, float]] = []
    for _, rep in fy_reports.iterrows():
        adsh, own_period = rep['adsh'], int(rep['period'])
        qdf = _load_quarter_tags(rep['fullPath'])
        val = _own_period_value(qdf, adsh, own_period, _NI_TAGS, qtrs=4)
        if val is not None:
            annual_list.append((own_period, val))
    annual_list.sort(key=lambda x: x[0], reverse=True)

    # ── Derive Q4 per FY — the only quarter that needs the closing 10-K ───────
    for idx, (fye_int, annual_ni) in enumerate(annual_list):
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

        q1_ni, q2_ni, q3_ni = fy_qs[0][1], fy_qs[1][1], fy_qs[2][1]
        q4_ni = round(annual_ni - q1_ni - q2_ni - q3_ni, 1)

        if _is_implausible_ni(q4_ni, annual_ni):
            continue

        seen.add(fye)
        results.append({'period_end': fye, 'net_income_m': _to_m(q4_ni), 'source': 'derived_q4'})

    results.sort(key=lambda r: r['period_end'], reverse=True)
    return results[:n_quarters]


# ── Public API ────────────────────────────────────────────────────────────────

def get_quarterly_net_margin(ticker: str, n_quarters: int = 8) -> list[dict]:
    """
    Local-DB equivalent of utils/edgar_net_margin.get_quarterly_net_margin() —
    same return shape (list of dicts, newest first, 'net_margin_pct' = NI/Rev x 100),
    sourced from the local secfsdstools parquet DB instead of live edgartools.

    Returns [] (never raises) if revenue or NI is unavailable for this ticker.
    """
    try:
        cik = get_cik(ticker)
        if not cik:
            return []
        cik_int = int(cik)

        ni_quarters = _quarterly_ni_secfs(cik_int, n_quarters)
        if not ni_quarters:
            return []

        rev_quarters = get_quarterly_revenue(ticker, n_quarters=n_quarters)
        if not rev_quarters:
            return []
        rev_by_period = {r['period_end']: r for r in rev_quarters}

        results: list[dict] = []
        for ni_item in ni_quarters:
            period = ni_item['period_end']
            rev_item = rev_by_period.get(period)
            if rev_item is None:
                continue
            revenue_m = rev_item['revenue_m']
            if not revenue_m:
                continue
            net_margin_pct = round((ni_item['net_income_m'] / revenue_m) * 100, 2)
            source = ('derived_q4'
                      if 'derived' in ni_item['source'] or 'derived' in rev_item['source']
                      else '10-Q')
            results.append({
                'ticker': ticker, 'period_end': period,
                'fiscal_quarter': rev_item.get('fiscal_quarter'),
                'net_margin_pct': net_margin_pct, 'source': source,
            })

        results.sort(key=lambda r: r['period_end'], reverse=True)
        return results[:n_quarters]
    except Exception as exc:
        log.warning("secfs_net_margin: get_quarterly_net_margin('%s') failed: %s", ticker, exc)
        return []


def get_quarterly_net_margin_pct(ticker: str, n_quarters: int = 4) -> list[float]:
    """
    Last n_quarters (default 4) of Net Profit Margin % for ticker, ascending
    (most recent last), sourced from the local secfsdstools parquet DB.

    Returns [] (never raises) when:
      - fewer than 3 quarters of margin data are available locally
      - the most recent available quarter is older than 365 days (local bulk
        dataset is stale — caller should fall back to utils/edgar_net_margin.py)
      - any exception occurs
    """
    try:
        cik = get_cik(ticker)
        if not cik:
            return []

        # Fast fail: skip the expensive NI + revenue extraction entirely if
        # the latest 10-K on file is already stale.
        proxy = latest_filing_period(int(cik))
        if proxy is None or (date.today() - proxy).days > 365:
            return []

        raw = get_quarterly_net_margin(ticker, n_quarters=n_quarters + 1)
        if len(raw) < 3:
            return []

        most_recent = max(r['period_end'] for r in raw)
        if (date.today() - most_recent).days > 365:
            return []

        ascending = sorted(raw, key=lambda r: r['period_end'])
        return [r['net_margin_pct'] for r in ascending[-n_quarters:]]
    except Exception as exc:
        log.warning("secfs_net_margin: get_quarterly_net_margin_pct('%s') failed: %s", ticker, exc)
        return []
