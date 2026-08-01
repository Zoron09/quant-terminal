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
depend on that order). All EPS fields stay empty exactly like the old engine's
output.

Raw NI is no longer empty: 'ni'/'ni_end_dates' now carry the real per-quarter
net income already sitting on each MarginPoint, alongside three additions —
'rev_sources'/'ni_sources' (per-quarter provenance, the un-flattened form of
the 'sources' summary, which is still emitted unchanged) and 'ni_restated'/
'ni_restated_value' (surfacing that a later filing revised a quarter's net
income, and the corrected figure). Purely additive: no existing field was
removed or renamed, and no reported revenue or margin value changed.
ni_plausible/revenue_plausible remain deliberately unexposed.

Banks: the pipeline refuses bank/depository tickers (their revenue can be
silently wrong under standard tags — confirmed on FULT). These return
status='excluded_bank' so the UI can show an explicit state, never a silent
disappearance.
"""
import logging
import threading
from datetime import date
from typing import Optional

from code33 import edgar_fill
from code33.net_margin import pair_margin_series
from code33.pipeline import get_complete_net_income_series, get_complete_revenue_series

log = logging.getLogger(__name__)

CACHE_VERSION = 'v32-code33-vendored'

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


_YOY_MIN_GAP_DAYS = 330
_YOY_MAX_GAP_DAYS = 400


def _yoy_miss_cause(rev_points: list, idx: int) -> Optional[str]:
    """Why yoy_for() could not produce a YoY for rev_points[idx].

    Mirrors yoy_for's walk exactly (same window, same falsy-prior test) so the
    diagnosis can never disagree with the number actually emitted. Returns None
    when a YoY IS computable — i.e. there is no miss to explain.
    """
    cur = rev_points[idx]
    for prior in rev_points[idx + 1:]:
        gap = (cur.period_end - prior.period_end).days
        if _YOY_MIN_GAP_DAYS <= gap <= _YOY_MAX_GAP_DAYS:
            return None if prior.value else 'zero_base'
        if gap > _YOY_MAX_GAP_DAYS:
            return 'year_ago_missing'
    return 'history_too_short'


def _diagnose_insufficient(all_rev_points: list, rev_points: list,
                           display_asc: list, rev_yoy: list, npm_vals: list) -> str:
    """Root cause for a ticker _c33_status called 'insufficient' on the SUCCESS
    path — both series pulled fine, but a leg never reached the 3 clean values
    the 3-consecutive-quarter Code 33 window needs.

    This path used to hardcode excluded_reason='' and every such ticker landed
    in one anonymous bucket (11 of 540 on the last full scan, all reported as
    'insufficient (unspecified)'), which told the operator nothing and gave the
    circuit breaker no cause to group on. Causes below are ordered
    most-explanatory first; each was confirmed against real traced tickers.
    """
    n_yoy = len([x for x in rev_yoy if x is not None])
    n_npm = len(npm_vals)  # already compacted upstream — no Nones to filter

    # 1. No revenue at all. Checked first because it breaks BOTH legs at once
    #    and is a property of the company, not a data defect: net margin is
    #    undefined against a zero denominator (net_margin.py guards revenue!=0)
    #    and so is YoY against a zero base. Verified against live EDGAR on
    #    RVMD/DNLI/SYRE — they file a revenue line reporting exactly $0.00.
    blank = sum(1 for p in all_rev_points if p.value is None or p.value == 0)
    if all_rev_points and blank * 2 >= len(all_rev_points):
        return (f"no reported revenue in {blank} of {len(all_rev_points)} quarters "
                f"- net margin and YoY are undefined against a zero base")

    # 2. Revenue side is fine and it is the margin leg that is short, so net
    #    income is the missing ingredient (revenue here is present and non-zero).
    if n_npm < 3 <= n_yoy:
        return (f"only {n_npm} of 3 quarters have a usable net margin "
                f"- net income missing for {len(display_asc) - n_npm} of "
                f"{len(display_asc)} revenue quarters")

    # 3. The YoY leg is short. Three genuinely different causes hide here, so
    #    report which one actually dominates rather than lumping them.
    causes: dict = {}
    for p in display_asc:
        cause = _yoy_miss_cause(rev_points, rev_points.index(p))
        if cause:
            causes[cause] = causes.get(cause, 0) + 1

    top = max(causes, key=causes.get) if causes else 'history_too_short'
    hits = causes.get(top, 0)
    if top == 'year_ago_missing':
        detail = (f"year-ago quarter missing for {hits} of {len(display_asc)} "
                  f"quarters")
    elif top == 'zero_base':
        detail = (f"year-ago revenue is zero for {hits} of {len(display_asc)} "
                  f"quarters")
    else:
        detail = (f"only {len(rev_points)} quarters of revenue filings "
                  f"- 7+ needed to form 3 year-over-year pairs")

    also = " (net margin also short)" if n_npm < 3 else ""
    return f"only {n_yoy} of 3 revenue YoY comparisons available - {detail}{also}"


def _empty_result(status: str, reason: str = '') -> dict:
    return {
        'eps': [], 'rev': [], 'ni': [],
        'eps_end_dates': [], 'rev_end_dates': [], 'ni_end_dates': [],
        'eps_yoy': [], 'rev_yoy': [],
        'eps_labels': [], 'rev_labels': [],
        'npm': [], 'npm_labels': [], 'npm_ends': [],
        'sources': {'rev': reason or status, 'ni': reason or status},
        'rev_sources': [], 'ni_sources': [],
        'ni_restated': [], 'ni_restated_value': [],
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


def normalize_ticker(ticker: str) -> str:
    """Share-class notation differs by source: screener exports and most data
    vendors use a dot (MOG.A, BRK.B), SEC's company_tickers.json uses a hyphen
    (MOG-A, BRK-B). Without this, every dual-class ticker silently fails CIK
    resolution and lands in 'insufficient' looking like missing data."""
    return ticker.strip().upper().replace('.', '-')


def get_code33_data(ticker: str, cache_v: str = CACHE_VERSION, n_quarters: int = 8) -> dict:
    """Same contract as the old engine: never raises, ascending arrays.

    cache_v is accepted for signature compatibility; the pipeline has no
    in-dict cache layer (endpoint-level TICKER_CACHE still applies upstream).
    """
    try:
        with _PIPELINE_LOCK:
            return _get_code33_data_inner(normalize_ticker(ticker), n_quarters)
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

    # No sector/industry gate here by design. Minervini treats utilities and
    # late-cycle names as sectors Code 33's own growth and margin criteria
    # filter out on the numbers, so blocking them before scoring pre-empts that
    # judgement. A gate plus informational-only flags were both tried and both
    # removed on 2026-08-01 — the flags cost a yfinance .info call per ticker
    # and nothing consumed them. The bank exclusion above is deliberately NOT
    # the same case: banks are refused for a proven data-correctness fault.

    # +4 quarters so every displayed quarter has a year-ago for YoY.
    pull = n_quarters + 4
    rev_series = get_complete_revenue_series(ticker, quarters=pull)
    if rev_series.series_flag is not None and not rev_series.points:
        return _empty_result('insufficient', rev_series.series_flag)

    rev_points = [p for p in rev_series.points if p.value is not None]  # newest first
    if len(rev_points) < 5:
        return _empty_result('insufficient', f'only {len(rev_points)} usable revenue quarters')

    # Reuse rev_series instead of calling get_complete_net_margin(), which would
    # rebuild the SAME revenue series from scratch — including repeating its
    # live-EDGAR gap fill. This is not an approximation: get_complete_net_margin
    # is literally
    #     revenue_series = get_complete_revenue_series(ticker, quarters)
    #     ni_series      = get_complete_net_income_series(ticker, quarters)
    #     pair_margin_series(revenue_series, ni_series,
    #                        revenue_series.cik or ni_series.cik, quarters)
    # and it is called with the same `quarters=pull` used above, so its first
    # line reproduces rev_series exactly. The three lines below are that body
    # with the duplicate build dropped; pair_margin_series is pure (reads only
    # the two series it is handed), so the paired output is unchanged.
    #
    # NOTE: this mirrors get_complete_net_margin's composition rather than
    # calling it. If code33-screener ever changes how that function builds or
    # pairs its legs, this must be re-synced — it will not fail loudly.
    # Fixing it inside code33-screener (e.g. an optional revenue_series
    # parameter) would remove that coupling, but that repo is off-limits from
    # quant-terminal sessions per CLAUDE.md rule 1.
    ni_series = get_complete_net_income_series(ticker, quarters=pull)
    margin_series = pair_margin_series(
        rev_series, ni_series, rev_series.cik or ni_series.cik, pull)
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

    def margin_point_for(rev_point):
        # Returns the whole MarginPoint, not just its percentage — the point
        # also carries net_income, ni_source and the restatement flags, which
        # used to be discarded here. Pairing logic is unchanged.
        return min(
            (m for m in margin_points
             if abs((m.period_end - rev_point.period_end).days) <= _PAIR_TOLERANCE_DAYS),
            key=lambda m: abs((m.period_end - rev_point.period_end).days),
            default=None,
        )

    # Build ascending (oldest first, newest LAST) — the order the old engine
    # emitted and /api/scan + /api/peers depend on.
    display_asc = list(reversed(display))
    rev_vals = [p.value for p in display_asc]
    rev_ends = [p.period_end.isoformat() for p in display_asc]
    rev_labels = [_fq_label(p.fy, p.fp) for p in display_asc]
    rev_yoy = [yoy_for(rev_points.index(p)) for p in display_asc]

    # Per-quarter revenue provenance, parallel to rev/rev_end_dates/rev_labels.
    # Upstream vocabulary is emitted verbatim rather than relabelled:
    # 'reported' = read from the secfsdstools bulk dataset, 'edgartools' = live
    # gap fill, 'derived_fy_minus_quarters' = Q4 back-solved from the 10-K.
    rev_sources = [p.source for p in display_asc]

    # ni_* and npm_* run strictly parallel — same quarters, same order, same
    # length — since both are appended only when a quarter has a paired margin.
    npm_vals, npm_ends, npm_labels = [], [], []
    ni_vals, ni_ends, ni_sources = [], [], []
    ni_restated, ni_restated_value = [], []
    for p in display_asc:
        mp = margin_point_for(p)
        if mp is not None and mp.net_margin_pct is not None:
            npm_vals.append(mp.net_margin_pct)
            npm_ends.append(p.period_end.isoformat())
            npm_labels.append(_fq_label(p.fy, p.fp))
            ni_vals.append(mp.net_income)
            ni_ends.append(p.period_end.isoformat())
            ni_sources.append(mp.ni_source)
            # True when a later filing revised this quarter's net income;
            # ni_restated_value carries the corrected figure. The engine still
            # reports the as-first-filed number in ni — this only surfaces that
            # a revision exists, it does not change any reported value.
            ni_restated.append(mp.ni_restated)
            ni_restated_value.append(mp.ni_restated_value)

    status, _d1, _d2 = _c33_status(rev_yoy, npm_vals)

    # _c33_status can still say 'insufficient' here even though both series
    # pulled cleanly — it needs 3 clean values per leg and a leg can fall short
    # for several genuinely different reasons. Name the actual one; a blank
    # reason on this path is what produced the unlabelled-failure bucket.
    reason = ''
    if status == 'insufficient':
        reason = _diagnose_insufficient(
            rev_series.points, rev_points, display_asc, rev_yoy, npm_vals)
        log.info("code33_adapter: %s insufficient - %s", ticker, reason)

    def _src_summary(points, attr):
        # QuarterPoint exposes .source; MarginPoint exposes .revenue_source /
        # .ni_source (it pairs two independently-sourced legs) — no shared attr.
        srcs = {getattr(p, attr) for p in points}
        return '+'.join(sorted(srcs)) if srcs else 'insufficient'

    return {
        'eps': [], 'rev': rev_vals, 'ni': ni_vals,
        'eps_end_dates': [], 'rev_end_dates': rev_ends, 'ni_end_dates': ni_ends,
        'eps_yoy': [], 'rev_yoy': rev_yoy,
        'eps_labels': [], 'rev_labels': rev_labels,
        'npm': npm_vals, 'npm_labels': npm_labels, 'npm_ends': npm_ends,
        # Collapsed series-level summary kept verbatim for existing callers;
        # rev_sources/ni_sources below are the per-quarter view it flattens.
        'sources': {
            'rev': _src_summary(display_asc, 'source'),
            'ni': _src_summary(margin_points, 'ni_source'),
        },
        'rev_sources': rev_sources, 'ni_sources': ni_sources,
        'ni_restated': ni_restated, 'ni_restated_value': ni_restated_value,
        'is_us': True, 'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': status,
        'excluded_reason': reason,
        'eps_prior_vals': [], 'eps_sources': [],
    }
