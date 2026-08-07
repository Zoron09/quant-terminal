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


# Code 33's acceleration window. CODE33_SPEC.md §2.1-2.2 is explicit: 8 raw
# quarters -> 4 YoY rates -> 3 acceleration jumps, and it names 3 rates / 2 jumps
# as NOT enough ("With only 6 raw quarters you get 3 YoY rates = only 2
# acceleration jumps = NOT enough for Code 33"). The original port checked
# exactly that rejected configuration, which is how DELL scored green off
# 10.83 -> 39.48 -> 87.54: the transition INTO that window, 18.98 -> 10.83, is a
# deceleration and nothing ever looked at it. Same shape confirmed on IESC
# (margin leg) and RNG (revenue leg).
#
# The 4th rate was already in hand — the adapter pulls n_quarters+4 and emits a
# YoY for all 8 displayed quarters, so this reads data that was always present
# rather than fetching more. Same class of fix as the GE restatement one.
_ACCEL_RATES = 4

# Scoreability floor, deliberately left at 3 and NOT raised to _ACCEL_RATES.
# Raising it would reclassify short-history tickers red -> insufficient, which is
# a change to the failure taxonomy (and would invalidate _diagnose_insufficient's
# "of 3" wording), not to the acceleration check this fix is about. A ticker with
# only 3 rates still cannot reach green below — proving 3 jumps requires 4 rates —
# so the spec's bar is enforced without altering how anything gets excluded.
_MIN_RATES = 3


def _c33_status(rev_rates: list, npm_vals: list = None) -> tuple:
    """(status, d1, d2) — green/yellow/red/insufficient.

    Code 33 (EPS removed from the signal — Revenue + Net Margin only) requires
    BOTH metrics to accelerate simultaneously across the 4-rate window:
      - Revenue YoY growth RATE rising every quarter
      - Net Profit Margin rising every quarter

    Acceleration is the FIRST derivative only: each rate must be higher than the
    one before it. There is NO requirement that the jumps themselves grow. The
    old port demanded `d2 >= d1` for green — a second-derivative test that is not
    part of Minervini's definition; removed 2026-08-06 after confirmation against
    his source material.

    Status rules:
      GREEN  = a full 4-rate window on both metrics, all 3 transitions positive
      RED    = any revenue rate negative, or any negative transition on either
               metric anywhere in the window
      YELLOW = neither (see the boundary note at the bottom of this function)
    """
    def _window(arr):
        if not arr: return None
        clean = [x for x in arr if x is not None]
        return clean[-_ACCEL_RATES:] if len(clean) >= _MIN_RATES else None

    def _deltas(w):
        return [w[i] - w[i - 1] for i in range(1, len(w))]

    rev_w = _window(rev_rates)
    npm_w = _window(npm_vals) if npm_vals else None

    if rev_w is None or npm_w is None:
        return 'insufficient', None, None

    # Sign gate: only the NEWEST rate has to be positive.
    #
    # This used to be `any(r < 0 for r in rev_w)` — one negative rate ANYWHERE in
    # the window was an instant reject, before the acceleration test ever ran.
    # That contradicts Minervini's own worked Code 33 example (Trade Like a Stock
    # Market Wizard, ch. 8 "The Code 33"), whose qualifying revenue sequence is
    # -22% -> +3% -> +16% -> +38%. It starts negative, and the old gate threw it
    # out on the first element. His EPS example starts at -34% and fails the same
    # way. The gate was never a data guard — it entered in b565b72 (2026-06-23)
    # commented "Rev rates must all be positive (negative = pre-profit /
    # declining)", citing a CLAUDE.md section that no longer exists, and
    # CODE33_SPEC.md never required it either (§1 is a pure ordering condition,
    # and §5 explicitly COMPUTES AND KEEPS sign-flipped rates, merely labelling
    # them [NM]).
    #
    # But the newest rate must still be positive. The book does not spell that
    # out, yet the methodology points hard at it: it wants real revenue GROWTH,
    # not merely less shrinkage, and for turnarounds it demands current results be
    # strongly positive (+100%-ish), not just improving. A sequence like
    # -50 -> -40 -> -30 -> -20 accelerates on every step while revenue is still
    # falling year-over-year in every quarter of the window — improvement, not
    # growth. His own example ends at +38%. So the test is the endpoint, not the
    # whole window.
    #
    # Revenue-only, matching how margin is already treated: margin has NO sign
    # gate at all, because -6.42 -> -4.49 -> -2.57 -> -2.32 is genuine margin
    # expansion (XMTR scores GREEN on exactly that). Unchanged here.
    if rev_w[-1] < 0:
        return 'red', None, None

    rev_d, npm_d = _deltas(rev_w), _deltas(npm_w)
    # Signature compatibility: the two deltas the old 3-rate check returned are
    # the last two here. Nothing consumes them — the adapter discards both.
    rev_d1, rev_d2 = rev_d[-2], rev_d[-1]

    if any(d < 0 for d in rev_d + npm_d):
        return 'red', rev_d1, rev_d2

    full_window = len(rev_w) == _ACCEL_RATES and len(npm_w) == _ACCEL_RATES
    if full_window and all(d > 0 for d in rev_d + npm_d):
        return 'green', rev_d1, rev_d2

    # YELLOW is NOT spec-defined — CODE33_SPEC.md §3 has ACTIVE/BROKEN/NOT ACTIVE,
    # not a three-colour badge, and reconciling those vocabularies is deliberately
    # out of scope for this fix. Under the corrected logic yellow means "not
    # disqualified, but not a clean pass either", which is exactly two cases:
    #   - a flat transition (delta == 0): not a decline, so not red; not an
    #     increase either, so acceleration is not satisfied
    #   - fewer than _ACCEL_RATES rates available: nothing decelerated, but 3
    #     jumps cannot be proven, so green is not earnable
    # Both are genuinely "unproven" rather than "failed", which is the tier
    # yellow already occupied.
    return 'yellow', rev_d1, rev_d2


_YOY_MIN_GAP_DAYS = 330
_YOY_MAX_GAP_DAYS = 400


def _yoy_value(point) -> Optional[float]:
    """The value to USE for a year-over-year comparison, which is not always the
    value to DISPLAY.

    When a later filing republishes a quarter on a different basis — a spinoff,
    divestiture or acquisition changes what the company consolidates — the
    engine keeps serving the as-first-filed figure (deliberate; see the AES
    entry in bug_report.md) but records the company's own recast figure on the
    point. Comparing an as-filed quarter against a recast one measures the
    corporate action, not the business: GE reported -43.3% YoY for 2024-09-30
    purely because its year-ago base still contained GE Vernova. On the recast
    basis that quarter is +5.8%.

    So a YoY uses the recast figure whenever the filer published one, on BOTH
    sides of the comparison, keeping the two ends on one basis. The displayed
    `rev` array is unchanged and stays as-filed; `rev_restated` /
    `rev_restated_value` in the payload say which quarters differ.

    Restatements run in both directions — DBRG and GE recast down after
    divesting, DBD and NVRI recast up — so this is deliberately not conditioned
    on the direction or size of the change, only on the filer having made one.
    """
    if point is None:
        return None
    if point.restated and point.restated_value is not None:
        return point.restated_value
    return point.value


def _yoy_miss_cause(rev_points: list, idx: int) -> Optional[str]:
    """Why yoy_for() could not produce a YoY for rev_points[idx].

    Mirrors yoy_for's walk exactly (same window, same falsy-prior test, and the
    same _yoy_value basis) so the diagnosis can never disagree with the number
    actually emitted. Returns None when a YoY IS computable — i.e. there is no
    miss to explain.
    """
    cur = rev_points[idx]
    for prior in rev_points[idx + 1:]:
        gap = (cur.period_end - prior.period_end).days
        if _YOY_MIN_GAP_DAYS <= gap <= _YOY_MAX_GAP_DAYS:
            return None if _yoy_value(prior) else 'zero_base'
        if gap > _YOY_MAX_GAP_DAYS:
            return 'year_ago_missing'
    return 'history_too_short'


def _blank_revenue_count(all_rev_points: list) -> int:
    """Quarters carrying no revenue at all. Counts BOTH shapes deliberately:
      value is None -> no revenue concept filed at all (SLXN)
      value == 0    -> a revenue concept filed as exactly $0.00 (RVMD/DNLI/SYRE)
    """
    return sum(1 for p in all_rev_points if p.value is None or p.value == 0)


def _is_pre_revenue(all_rev_points: list) -> bool:
    """At least half the pulled quarters have no revenue."""
    return bool(all_rev_points) and _blank_revenue_count(all_rev_points) * 2 >= len(all_rev_points)


def _pre_revenue_reason(all_rev_points: list) -> str:
    blank = _blank_revenue_count(all_rev_points)
    return (f"no reported revenue in {blank} of {len(all_rev_points)} quarters "
            f"- net margin and YoY are undefined against a zero base")


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
    if _is_pre_revenue(all_rev_points):
        return _pre_revenue_reason(all_rev_points)

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
        'rev_restated': [], 'rev_restated_value': [],
        'ni_restated': [], 'ni_restated_value': [],
        'is_us': True, 'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': status,
        'excluded_reason': reason,
        'eps_prior_vals': [], 'eps_sources': [],
    }


# SEC's fiscal-period vocabulary has no 'Q4'. A fiscal year's fourth quarter is
# only ever reported on the 10-K, which carries fp='FY', so passing fp straight
# through rendered a discrete quarter as 'FY FY24' — reading as if the value
# were the full year when it is not: the Q4 figure is back-solved
# (derived_fy_minus_quarters) or read as that filing's own discrete period.
# 'Q4' is the honest label, and it matches what the engine already assumes
# internally — quarterly_engine._attach_plausibility groups siblings on
# fp in ('Q1','Q2','Q3'), i.e. it treats 'FY' as the Q4 slot.
_FP_ALIASES = {'FY': 'Q4'}


def _fq_label(fy, fp) -> str:
    if fy is None or fp is None:
        return ''
    return f"{_FP_ALIASES.get(fp, fp)} FY{str(fy)[2:]}"


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
        # A company filing NO revenue concept at all arrives here with every
        # point value=None, stripped by the filter above — the same real-world
        # condition as the $0.00 filers, which keep value=0.0, survive, and are
        # correctly diagnosed pre-revenue on the success path. Route only that
        # case through the same diagnosis (tested against the UNFILTERED series,
        # since the filter is exactly what hides the evidence); every other
        # short-history reason keeps its existing message verbatim.
        if _is_pre_revenue(rev_series.points):
            return _empty_result('insufficient', _pre_revenue_reason(rev_series.points))
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
        # Both ends go through _yoy_value so the comparison stays on ONE basis
        # when a filer has recast either quarter. See _yoy_value for why.
        cur = rev_points[idx_in_rev_points]
        cur_v = _yoy_value(cur)
        for prior in rev_points[idx_in_rev_points + 1:]:
            gap = (cur.period_end - prior.period_end).days
            if _YOY_MIN_GAP_DAYS <= gap <= _YOY_MAX_GAP_DAYS:
                prior_v = _yoy_value(prior)
                if prior_v and cur_v is not None:
                    return round((cur_v - prior_v) / abs(prior_v) * 100, 2)
                return None
            if gap > _YOY_MAX_GAP_DAYS:
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

    # Revenue restatement flags. Computed upstream all along and discarded here
    # until 2026-08-02 — the same discard class as the ni_restated fix. Exposed
    # because rev_yoy is now computed on the recast basis while `rev` stays
    # as-filed: without these the payload could not explain why the two disagree
    # on a ticker like GE. True means a later filing republished that quarter on
    # a different basis; rev_restated_value carries the figure rev_yoy used.
    #
    # LENGTH NOTE — these two arrays are DELIBERATELY LONGER than rev /
    # rev_end_dates / rev_sources, and must not be zipped with them.
    # The adapter pulls n_quarters + 4 quarters so every displayed quarter has a
    # year-ago base; only the newest n_quarters are displayed. A restatement on
    # a BASE-ONLY quarter still changes rev_yoy, so restricting these arrays to
    # the displayed window hid exactly the case they exist to explain (found on
    # PFE: all 8 displayed flags False, yet two YoY values moved because their
    # bases — outside the window — were recast).
    #
    # Both arrays are ascending (oldest first), same order as rev. Mapping:
    #   rev_restated[-len(rev):]   <-> the displayed quarters, aligned to rev
    #   rev_restated[:-len(rev)]   <-> older base-only quarters, never displayed
    all_asc = list(reversed(rev_points))
    rev_restated = [bool(p.restated) for p in all_asc]
    rev_restated_value = [p.restated_value if p.restated else None for p in all_asc]

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
        'rev_restated': rev_restated, 'rev_restated_value': rev_restated_value,
        'ni_restated': ni_restated, 'ni_restated_value': ni_restated_value,
        'is_us': True, 'sector_excluded': False, 'excluded_sector_name': '',
        'is_reit': False,
        'status': status,
        'excluded_reason': reason,
        'eps_prior_vals': [], 'eps_sources': [],
    }
