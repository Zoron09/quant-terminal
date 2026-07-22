"""Adapter between the validated code33-screener pipeline and quant-terminal's
existing API contract.

Replaces the old utils/code33_engine.py (deleted in the code33-swap branch).
Data comes from the code33 package (pip install -e ../code33-screener):
secfsdstools primary, live-EDGAR gap fill for quarters the bulk mirror doesn't
have yet — the pipeline validated against SEC filings and a 568-ticker run.

Concurrency contract (do not weaken):
  - The pipeline is strictly sequential by design; its in-process caches were
    never built or tested for threaded use.
  - _PIPELINE_LOCK serializes EVERY call into the pipeline server-wide — all
    endpoints and the background scan job funnel through get_code33_data(),
    so only one pipeline call executes at a time, globally.
  - Endpoints should call this via a thread offload (run_in_threadpool) so the
    event loop stays responsive; the lock preserves one-at-a-time execution.

Output shape mirrors the old get_code33_data() dict (ascending arrays, oldest
first, newest LAST — /api/scan's safe3() and /api/peers' reversed() lookups
depend on that order). Raw NI and all EPS fields stay empty exactly like the
old engine's output.

Banks: the pipeline refuses bank/depository tickers (their revenue can be
silently wrong under standard tags — confirmed on FULT). These return
status='excluded_bank' so the UI can show an explicit state, never a silent
disappearance.
"""
import logging
import threading
from datetime import date

from code33 import edgar_fill
from code33.pipeline import get_complete_net_margin, get_complete_revenue_series

log = logging.getLogger(__name__)

CACHE_VERSION = 'v31-code33-screener'

_PIPELINE_LOCK = threading.Lock()

_PAIR_TOLERANCE_DAYS = 25  # matches code33.edgar_fill.MATCH_TOLERANCE_DAYS


def _c33_status(rev_rates: list, npm_vals: list = None) -> tuple:
    """(status, d1, d2) — green/yellow/red/insufficient.

    Ported VERBATIM from the old utils/code33_engine.py — the 3-state badge
    semantics the frontend renders. Code 33 (EPS removed from the signal —
    Revenue + Net Margin only) requires BOTH simultaneously for 3 consecutive
    quarters:
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

    if rev3 is None or npm3 is None:
        return 'insufficient', None, None

    if any(r < 0 for r in rev3):
        return 'red', None, None

    all_d = []
    for m in [rev3, npm3]:
        all_d.append((m[1] - m[0], m[2] - m[1]))

    rev_d1, rev_d2 = all_d[0]

    if any(d1 < 0 or d2 < 0 for d1, d2 in all_d):
        return 'red', rev_d1, rev_d2

    if all(d2 >= d1 for d1, d2 in all_d):
        return 'green', rev_d1, rev_d2

    return 'yellow', rev_d1, rev_d2


def _empty_result(status: str, reason: str = '') -> dict:
    return {
        'eps': [], 'rev': [], 'ni': [],
        'eps_end_dates': [], 'rev_end_dates': [], 'ni_end_dates': [],
        'eps_yoy': [], 'rev_yoy': [],
        'eps_labels': [], 'rev_labels': [],
        'npm': [], 'npm_labels': [], 'npm_ends': [],
        'sources': {'rev': reason or status, 'ni': reason or status},
        'is_us': True, 'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': status,
        'excluded_reason': reason,
        'eps_prior_vals': [], 'eps_sources': [],
    }


def _fq_label(fy, fp) -> str:
    if fy is None or fp is None:
        return ''
    return f"{fp} FY{str(fy)[2:]}"


def get_code33_data(ticker: str, cache_v: str = CACHE_VERSION, n_quarters: int = 8) -> dict:
    """Same contract as the old engine: never raises, ascending arrays.

    cache_v is accepted for signature compatibility; the pipeline has no
    in-dict cache layer (endpoint-level TICKER_CACHE still applies upstream).
    """
    try:
        with _PIPELINE_LOCK:
            return _get_code33_data_inner(ticker.upper(), n_quarters)
    except Exception:
        log.exception("code33_adapter: %s unhandled error", ticker)
        return _empty_result('insufficient', 'unhandled error')


def _get_code33_data_inner(ticker: str, n_quarters: int) -> dict:
    # Bank check first — refuse rather than score on possibly-wrong data.
    try:
        bank_tags = edgar_fill.bank_signal_tags(ticker)
    except Exception:
        bank_tags = []
    if bank_tags:
        log.info("code33_adapter: %s excluded (bank tags: %s)", ticker, bank_tags)
        return _empty_result('excluded_bank', 'bank/depository institution — not yet supported')

    # +4 quarters so every displayed quarter has a year-ago for YoY.
    pull = n_quarters + 4
    rev_series = get_complete_revenue_series(ticker, quarters=pull)
    if rev_series.series_flag is not None and not rev_series.points:
        return _empty_result('insufficient', rev_series.series_flag)

    rev_points = [p for p in rev_series.points if p.value is not None]  # newest first
    if len(rev_points) < 5:
        return _empty_result('insufficient', f'only {len(rev_points)} usable revenue quarters')

    margin_series = get_complete_net_margin(ticker, quarters=pull)
    margin_points = [p for p in margin_series.points if p.net_margin_pct is not None]

    display = rev_points[:n_quarters]  # newest first

    def yoy_for(idx_in_rev_points: int):
        cur = rev_points[idx_in_rev_points]
        for prior in rev_points[idx_in_rev_points + 1:]:
            gap = (cur.period_end - prior.period_end).days
            if 330 <= gap <= 400:
                if prior.value:
                    return round((cur.value - prior.value) / abs(prior.value) * 100, 2)
                return None
            if gap > 400:
                return None
        return None

    def margin_for(rev_point):
        best = min(
            (m for m in margin_points
             if abs((m.period_end - rev_point.period_end).days) <= _PAIR_TOLERANCE_DAYS),
            key=lambda m: abs((m.period_end - rev_point.period_end).days),
            default=None,
        )
        return best.net_margin_pct if best is not None else None

    # Build ascending (oldest first, newest LAST) — the order the old engine
    # emitted and /api/scan + /api/peers depend on.
    display_asc = list(reversed(display))
    rev_vals = [p.value for p in display_asc]
    rev_ends = [p.period_end.isoformat() for p in display_asc]
    rev_labels = [_fq_label(p.fy, p.fp) for p in display_asc]
    rev_yoy = [yoy_for(rev_points.index(p)) for p in display_asc]

    npm_vals, npm_ends, npm_labels = [], [], []
    for p in display_asc:
        m = margin_for(p)
        if m is not None:
            npm_vals.append(m)
            npm_ends.append(p.period_end.isoformat())
            npm_labels.append(_fq_label(p.fy, p.fp))

    status, _d1, _d2 = _c33_status(rev_yoy, npm_vals)

    def _src_summary(points, attr):
        # QuarterPoint exposes .source; MarginPoint exposes .revenue_source /
        # .ni_source (it pairs two independently-sourced legs) — no shared attr.
        srcs = {getattr(p, attr) for p in points}
        return '+'.join(sorted(srcs)) if srcs else 'insufficient'

    return {
        'eps': [], 'rev': rev_vals, 'ni': [],
        'eps_end_dates': [], 'rev_end_dates': rev_ends, 'ni_end_dates': [],
        'eps_yoy': [], 'rev_yoy': rev_yoy,
        'eps_labels': [], 'rev_labels': rev_labels,
        'npm': npm_vals, 'npm_labels': npm_labels, 'npm_ends': npm_ends,
        'sources': {
            'rev': _src_summary(display_asc, 'source'),
            'ni': _src_summary(margin_points, 'ni_source'),
        },
        'is_us': True, 'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': status,
        'excluded_reason': '',
        'eps_prior_vals': [], 'eps_sources': [],
    }
