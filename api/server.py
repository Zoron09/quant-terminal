from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
import io
import sys
import os
import re
import math
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
from functools import lru_cache
from datetime import datetime
from pathlib import Path
import time

# tools/ — not served by StaticFiles, unlike frontend/ (mounted at /static below)
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.code33_adapter import get_code33_data, CACHE_VERSION, normalize_ticker
from fastapi.concurrency import run_in_threadpool

TICKER_CACHE = {}

# One dict, four different freshness needs. Every endpoint declared its own
# window, but evict_cache() purged the whole dict on the shortest one, so any
# entry wanting to live longer than CACHE_TTL was deleted out from under its
# own check. /api/financials asked for 600s and never saw a hit past 300s —
# it recomputed a 3-4s payload (5 yfinance calls plus a 12-quarter engine
# pull that takes the adapter's global lock) every time.
#
# Raising the shared constant to 600 was the other option and is worse:
# CACHE_TTL is what /api/ticker serves live price out of, so a single number
# would have doubled price staleness to fix a financials problem. Each entry
# now expires on its own clock instead.
CACHE_TTL = 300            # /api/ticker — carries live price, stays short
CACHE_TTL_CHART = 300      # /api/chart
CACHE_TTL_FINANCIALS = 600 # /api/financials — expensive, changes quarterly
CACHE_TTL_NEWS = 120       # /api/news
# /api/peers is the most expensive endpoint in the app: it runs the engine
# pipeline once PER PEER (four of them) behind the adapter's global lock, and
# was recomputing all four on every single search. Peer membership comes from a
# hardcoded sector table and the peers' own quarterly filings — neither moves
# minute to minute, so it gets the long window rather than the price one.
CACHE_TTL_PEERS = 600      # /api/peers
# Institutional holdings come from 13F filings (quarterly); insider
# transactions from Form 4 (days). Nothing here justifies a 300s refresh.
CACHE_TTL_OWNERSHIP = 600  # /api/ownership


def _entry_ttl(key):
    """Per-entry lifetime, keyed off the prefix each endpoint already uses when
    it writes to TICKER_CACHE. Bare ticker symbols (no prefix) are /api/ticker."""
    if key.startswith('fin_'):
        return CACHE_TTL_FINANCIALS
    if key.startswith('news_'):
        return CACHE_TTL_NEWS
    if key.startswith('chart_'):
        return CACHE_TTL_CHART
    if key.startswith('peers_'):
        return CACHE_TTL_PEERS
    if key.startswith('own_'):
        return CACHE_TTL_OWNERSHIP
    return CACHE_TTL


def evict_cache():
    now = time.time()
    expired = [k for k, v in list(TICKER_CACHE.items()) if now - v[1] > _entry_ttl(k)]
    for k in expired: TICKER_CACHE.pop(k, None)


# ---------------------------------------------------------------------------
# yfinance crumb recovery
# ---------------------------------------------------------------------------
# Yahoo's quoteSummary endpoint — institutional holders, insider transactions
# and .info — is crumb-authenticated. Chart/history is NOT, which is why price
# and chart data kept working while everything below silently went empty.
#
# yfinance caches one crumb on a process-wide singleton (YfData, data.py:75)
# and _get_crumb_basic() (data.py:221) returns it whenever it is not None,
# without ever re-validating it. Once that crumb goes stale — or a burst of
# requests gets rate-limited while it is being fetched — every crumb-backed
# call fails for the rest of the process's lifetime, and only a restart fixes
# it. The failure is invisible: scrapers/holders.py:73 catches the resulting
# HTTPError and assigns empty DataFrames to all six holder fields, and
# scrapers/quote.py:597 does the same for .info, both because
# YfConfig.debug.hide_exceptions defaults to True (config.py:34). No exception
# ever reaches this file, so the endpoints returned empty payloads with a 200.
#
# _yf_force_fresh_crumb() drops the cached cookie+crumb so the next call
# fetches new ones. _yf_quote_summary() does exactly one such retry when a
# result comes back empty. A ticker that genuinely has no holders costs one
# extra request and still returns empty — the retry cannot invent data, it
# only rules out a stale crumb as the cause.

def _yf_force_fresh_crumb():
    """Clear the process-wide cached Yahoo cookie/crumb. Returns True if the
    reset went through. Best-effort by design: this reaches into yfinance
    internals, so a version bump that renames them must degrade to 'no retry',
    never to a 500."""
    try:
        from yfinance.data import YfData
        d = YfData()  # singleton — no args means "existing instance", no session reset
        with d._cookie_lock:
            d._cookie = None
            d._crumb = None
            d._cookie_strategy = 'basic'
        return True
    except Exception as e:
        print(f"[yfinance] crumb reset failed: {e}")
        return False


def _info_is_empty(d):
    """True when a .info payload came back with nothing identifying in it.
    shortName/longName are present on every healthy quoteSummary response;
    their absence means the fetch failed, not that the company has no name."""
    return not d or not (d.get('shortName') or d.get('longName'))


def _yf_quote_summary(symbol, extract, is_empty=None):
    """Run `extract` against a fresh yf.Ticker for `symbol`. If the result is
    empty (or the call raised), force a new crumb and try once more.

    The retry MUST build a new yf.Ticker: yfinance memoizes the parsed result
    on the instance (Holders._institutional, Quote._info), so reusing the same
    object would just replay the empty answer without re-requesting.

    Returns (result, retried). Exceptions on the second attempt propagate to
    the caller's handler — one silent swallow was the original bug."""
    empty = is_empty or (lambda r: not r)
    result = None
    try:
        result = extract(yf.Ticker(symbol))
        if not empty(result):
            return result, False
    except Exception as e:
        print(f"[yfinance] quoteSummary call failed for {symbol}: {e}")
    if not _yf_force_fresh_crumb():
        return result, False
    print(f"[yfinance] empty quoteSummary result for {symbol} — refetched crumb, retrying")
    return extract(yf.Ticker(symbol)), True


# ---------------------------------------------------------------------------
# Wealthsimple auto-refresh — background-only, cached-session-only.
# Never prompts for credentials (get_cached_api_or_none() has no input()/
# getpass() path at all). Fetch always runs off the event loop thread via
# a dedicated single-worker executor, and this endpoint's handler never
# calls .result()/await on it — it's genuinely fire-and-forget, not just
# offloaded-but-still-blocking (the /api/financials ThreadPoolExecutor
# pattern elsewhere in this file calls .result() synchronously inside an
# async def, which still blocks the single event loop for the fetch's
# full duration — not copying that here, since the whole point is that
# OTHER requests must keep working while a Wealthsimple fetch is in flight).
# ---------------------------------------------------------------------------

WS_REFRESH_INTERVAL_SECONDS = 300  # 5 min — manual trading activity doesn't
# change fast enough to need more, and ws_api has zero built-in rate-limit
# handling (confirmed during the hardening investigation), so erring toward
# fewer background calls is the safer default.

_ws_fetch_executor = ThreadPoolExecutor(max_workers=1)  # never more than one fetch in flight
_ws_fetch_lock = threading.Lock()
_ws_fetch_in_progress = False
_ws_last_fetch_attempt = 0.0
_ws_last_fetch_ok = None  # None = never attempted yet; True/False = last attempt's outcome


def _discover_ws_start_date():
    """Find the start date to reuse from the most recently modified
    ws_import_<start>_<end>.json already in tools/ — per CLAUDE.md rule 14,
    always reuse the same start date rather than a shifting window,
    otherwise FIFO leg-matching can pair the same closing leg with a
    different opener than a prior run did. Returns None if no dated export
    exists yet, meaning there's no established baseline to auto-refresh."""
    pattern = re.compile(r"^ws_import_(\d{4}-\d{2}-\d{2})_\d{4}-\d{2}-\d{2}\.json$")
    matches = []
    for f in TOOLS_DIR.glob("ws_import_*.json"):
        if f.name == "ws_import_latest.json":
            continue
        m = pattern.match(f.name)
        if m:
            matches.append((f.stat().st_mtime, m.group(1)))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    return matches[-1][1]


def _run_ws_background_fetch():
    """Runs on a worker thread. Never raises out to the executor — any
    failure (no session, network error, matching error) is caught and
    recorded, never crashes the thread pool or the server."""
    global _ws_fetch_in_progress, _ws_last_fetch_ok
    try:
        from tools.wealthsimple_export import run_export_with_cached_session
        start_date = _discover_ws_start_date()
        if start_date is None:
            _ws_last_fetch_ok = False
            return
        end_date = datetime.now().strftime("%Y-%m-%d")
        _ws_last_fetch_ok = run_export_with_cached_session(start_date, end_date)
    except Exception as e:
        print(f"[wealthsimple auto-fetch] failed: {e}")
        _ws_last_fetch_ok = False
    finally:
        with _ws_fetch_lock:
            _ws_fetch_in_progress = False


def _maybe_trigger_ws_refresh():
    """Fire-and-forget: submits a background fetch if the debounce interval
    has passed and nothing's already running. Never awaited/joined by the
    caller — the request handler returns immediately regardless."""
    global _ws_fetch_in_progress, _ws_last_fetch_attempt
    now = time.time()
    with _ws_fetch_lock:
        if _ws_fetch_in_progress:
            return
        if now - _ws_last_fetch_attempt < WS_REFRESH_INTERVAL_SECONDS:
            return
        _ws_fetch_in_progress = True
        _ws_last_fetch_attempt = now
    _ws_fetch_executor.submit(_run_ws_background_fetch)


@asynccontextmanager
async def _lifespan(app):
    """Start the News Scanner poller here rather than at import time.

    Under `--reload` this module is imported in more than one process (the
    reloader and the spawned worker both pull it in on Windows), so an
    import-time start produced TWO pollers and therefore double the call rate
    against SEC and Finnhub — measured, not theorised: the priming fetch logged
    twice. Startup runs only in the process that actually serves requests, so
    exactly one poller exists. Imported locally because api.news_scanner is
    registered at the bottom of this file.
    """
    from api.news_scanner import start_poller
    start_poller()
    yield


app = FastAPI(lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve HTML files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

@app.get("/screener")
async def screener():
    return FileResponse("frontend/index.html")

@app.get("/analysis")
async def analysis():
    return FileResponse("frontend/index.html")

@app.get("/journal")
async def journal():
    return FileResponse("frontend/journal.html")

@app.get("/api/journal/wealthsimple-latest")
async def wealthsimple_latest():
    """Serves whatever tools/wealthsimple_export.py has already written to
    disk — always immediately, never waiting on a network fetch. Separately
    (fire-and-forget, never awaited) triggers a debounced background
    refresh using ONLY the cached session — never prompts for credentials,
    never touches session.json beyond reading/refreshing it via the
    existing cached token. If there's no valid cached session, or the
    debounce interval hasn't passed, or a fetch is already running, this
    is a silent no-op and cached data is served exactly as before."""
    _maybe_trigger_ws_refresh()

    trades_file = TOOLS_DIR / "ws_import_latest.json"
    review_file = TOOLS_DIR / "needs_review.json"
    balances_file = TOOLS_DIR / "account_balances.json"
    positions_file = TOOLS_DIR / "open_positions.json"

    trades = None
    if trades_file.exists():
        try:
            trades = json.loads(trades_file.read_text())
        except Exception:
            trades = None

    needs_review = None
    if review_file.exists():
        try:
            needs_review = json.loads(review_file.read_text())
        except Exception:
            needs_review = None

    account_balances = None
    if balances_file.exists():
        try:
            account_balances = json.loads(balances_file.read_text())
        except Exception:
            account_balances = None

    open_positions = None
    if positions_file.exists():
        try:
            open_positions = json.loads(positions_file.read_text())
        except Exception:
            open_positions = None

    if trades is None and needs_review is None:
        return JSONResponse(
            {'error': 'No Wealthsimple export found. Run tools/wealthsimple_export.py first.'},
            status_code=404,
        )

    return JSONResponse({
        'trades': trades,
        'needs_review': needs_review,
        'account_balances': account_balances,
        'open_positions': open_positions,
        'live_sync': {
            'last_attempt': _ws_last_fetch_attempt or None,
            'last_attempt_ok': _ws_last_fetch_ok,
        },
    })

@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_csv(io.BytesIO(contents))
    
    sector_map = {}
    mcap_map = {}
    
    if 'Symbol' in df.columns and 'Sector' in df.columns:
        sector_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Sector'].fillna('Unknown')
        ))
    
    company_map = {}
    if 'Symbol' in df.columns and 'Description' in df.columns:
        company_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Description'].fillna('')
        ))

    if 'Symbol' in df.columns and 'Market capitalization' in df.columns:
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                if v >= 1e6:  return f"${v/1e6:.1f}M"
                return f"${v:,.0f}"
            except: return "N/A"
        mcap_map = {
            str(row['Symbol']).upper(): fmt_mcap(row['Market capitalization'])
            for _, row in df.iterrows()
        }

    tickers = df['Symbol'].str.upper().tolist() \
        if 'Symbol' in df.columns else []

    print(f"[SCAN] START - file received: {file.filename}")
    print(f"[SCAN] tickers count: {len(tickers)}")

    return _start_scan_job(tickers, sector_map, company_map, mcap_map)


# ── Background scan job — sequential, checkpointed, resumable ────────────────
# The pipeline is strictly sequential (never validated under concurrency), so
# a 300-500 ticker scan runs 1.5-5+ hours. One daemon thread walks the list,
# one ticker at a time, appending each result to a per-job checkpoint CSV as
# it lands. A scan interrupted by a server restart resumes from the checkpoint
# when the same ticker list is uploaded again (job identity = hash of the
# sorted ticker list). The frontend polls GET /api/scan/status for progress.
import csv as _csv
import hashlib
import time

SCAN_JOBS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'scan_jobs'
SCAN_FIELDS = ['ticker', 'status', 'rev_yoy', 'margin', 'reason']

# ── Circuit breaker ─────────────────────────────────────────────────────────
# Mirrors code33-screener/tools/universe_scan.py. A scan runs for hours; if
# something breaks systematically partway through (dataset gone stale, SEC
# rate-limiting, a whole sector hitting one tag gap), continuing just bakes
# the failure into the rest of the results. Two triggers:
#   1. the same root cause >BREAKER_CONSECUTIVE tickers in a row
#   2. one root cause dominating a broader stretch (>= BREAKER_WINDOW_HITS of
#      the last BREAKER_WINDOW), which catches a systematic problem that a
#      few interleaved successes would otherwise mask
# Tripping stops the job and leaves the checkpoint intact — nothing already
# completed is lost, and the same upload resumes from where it stopped.
BREAKER_CONSECUTIVE = 10
BREAKER_WINDOW = 30
BREAKER_WINDOW_HITS = 20

_scan_lock = threading.Lock()   # guards _scan_state / thread start, NOT the pipeline
_scan_state = {'running': False, 'job_id': None, 'total': 0, 'completed': 0,
               'passed': 0, 'excluded_banks': 0, 'insufficient': 0,
               'current_ticker': None, 'done': False, 'error': None,
               'stopped_early': False, 'stop_reason': None}
_scan_maps = {'sector': {}, 'company': {}, 'mcap': {}}


def _classify_failure(status: str, data: dict = None, exc: Exception = None) -> str:
    """Normalized root cause for a ticker that produced no usable verdict, or
    '' when the result is clean (green/yellow/red/excluded_bank all count as
    real answers). Normalized so variants of the same cause group together —
    'only 3 usable revenue quarters' and 'only 5 ...' must land in one bucket
    for the breaker to see the pattern."""
    if exc is not None:
        return f"exception: {type(exc).__name__}"
    if status != 'insufficient':
        return ''
    raw = ((data or {}).get('excluded_reason') or '').lower()
    if 'no 10-q/10-k filings' in raw:
        return 'no 10-Q/10-K filings in dataset'
    if 'usable revenue quarters' in raw:
        return 'insufficient revenue history'
    if 'could not resolve' in raw:
        return 'ticker/CIK resolution failed'
    if 'unhandled error' in raw:
        return 'pipeline unhandled error'
    # Causes raised by the success path (both series pulled, but a leg had
    # fewer than the 3 clean values _c33_status needs). Bucket names match
    # code33-screener's universe_scan.py taxonomy so the two projects'
    # failure reports stay comparable.
    if 'no reported revenue' in raw:
        return 'no reported revenue (pre-revenue company)'
    if 'usable net margin' in raw:
        return 'insufficient margin data'
    if 'year-ago quarter missing' in raw:
        return 'quarter sequence broken'
    if 'year-ago revenue is zero' in raw:
        return 'zero year-ago revenue'
    if 'quarters of revenue filings' in raw:
        return 'insufficient revenue history'
    if not raw:
        return 'insufficient (unspecified)'
    return f"other: {raw[:60]}"


def _safe3(lst):
    if not lst: return [0, 0, 0]
    lst = [x for x in lst if x is not None]
    if len(lst) < 3:
        lst = ([0] * (3 - len(lst))) + lst
    return [round(x, 1) for x in lst[-3:]]


def _job_checkpoint_path(job_id: str) -> Path:
    return SCAN_JOBS_DIR / f"scan_{job_id}.csv"


def _read_checkpoint(job_id: str) -> dict:
    path = _job_checkpoint_path(job_id)
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8') as fh:
        return {row['ticker']: row for row in _csv.DictReader(fh)}


def _scan_worker(job_id: str, tickers: list):
    done_rows = _read_checkpoint(job_id)
    path = _job_checkpoint_path(job_id)
    write_header = not path.exists()
    try:
        with path.open('a', newline='', encoding='utf-8') as fh:
            writer = _csv.DictWriter(fh, fieldnames=SCAN_FIELDS)
            if write_header:
                writer.writeheader()
                fh.flush()
            consecutive_reason, consecutive_count = None, 0
            recent_reasons = []
            tripped = None

            for t in tickers:
                if t in done_rows:
                    continue
                with _scan_lock:
                    _scan_state['current_ticker'] = t
                try:
                    # Adapter's internal lock serializes this against every
                    # other endpoint's pipeline call — strictly one at a time.
                    data = get_code33_data(t, CACHE_VERSION)
                    status = data.get('status', 'insufficient')
                    reason = _classify_failure(status, data=data)
                    row = {
                        'ticker': t, 'status': status,
                        'rev_yoy': ';'.join(str(x) for x in _safe3(data.get('rev_yoy', []))),
                        'margin': ';'.join(str(x) for x in _safe3(data.get('npm', []))),
                        'reason': reason,
                    }
                except Exception as e:
                    print(f"[SCAN ERROR] {t}: {e}")
                    reason = _classify_failure('insufficient', exc=e)
                    row = {'ticker': t, 'status': 'insufficient', 'rev_yoy': '',
                           'margin': '', 'reason': reason}
                writer.writerow(row)
                fh.flush()
                done_rows[t] = row
                with _scan_lock:
                    _scan_state['completed'] = len(done_rows)
                    if row['status'] in ('green', 'yellow'):
                        _scan_state['passed'] += 1
                    elif row['status'] == 'excluded_bank':
                        _scan_state['excluded_banks'] += 1
                    elif row['status'] == 'insufficient':
                        _scan_state['insufficient'] += 1

                # ── circuit breaker ──────────────────────────────────────
                reason = row['reason']
                if reason:
                    consecutive_count = consecutive_count + 1 if reason == consecutive_reason else 1
                    consecutive_reason = reason
                else:
                    consecutive_reason, consecutive_count = None, 0
                recent_reasons.append(reason)
                if len(recent_reasons) > BREAKER_WINDOW:
                    recent_reasons.pop(0)

                if consecutive_count > BREAKER_CONSECUTIVE:
                    tripped = (f"stopped early: {consecutive_count} tickers in a row failed with "
                               f"'{consecutive_reason}' (last: {t}) — systematic problem, not "
                               f"per-ticker noise. {len(done_rows)} results kept; re-upload the "
                               f"same list to resume.")
                elif len(recent_reasons) == BREAKER_WINDOW:
                    counts = {}
                    for r in recent_reasons:
                        if r:
                            counts[r] = counts.get(r, 0) + 1
                    if counts:
                        top_reason, top_n = max(counts.items(), key=lambda kv: kv[1])
                        if top_n >= BREAKER_WINDOW_HITS:
                            tripped = (f"stopped early: {top_n} of the last {BREAKER_WINDOW} tickers "
                                       f"failed with '{top_reason}' (last: {t}) — dominant failure "
                                       f"pattern. {len(done_rows)} results kept; re-upload the same "
                                       f"list to resume.")

                if tripped:
                    print(f"[SCAN] CIRCUIT BREAKER — {tripped}")
                    with _scan_lock:
                        _scan_state['running'] = False
                        _scan_state['current_ticker'] = None
                        _scan_state['stopped_early'] = True
                        _scan_state['stop_reason'] = tripped
                        _scan_state['error'] = tripped
                    return

        with _scan_lock:
            _scan_state['running'] = False
            _scan_state['done'] = True
            _scan_state['current_ticker'] = None
        print(f"[SCAN] COMPLETE - {len(done_rows)}/{len(tickers)} tickers")
    except Exception as e:
        with _scan_lock:
            _scan_state['running'] = False
            _scan_state['error'] = str(e)
        print(f"[SCAN] FATAL: {e}")


def _start_scan_job(tickers, sector_map, company_map, mcap_map):
    job_id = hashlib.sha1(','.join(sorted(set(tickers))).encode()).hexdigest()[:12]
    with _scan_lock:
        if _scan_state['running']:
            return JSONResponse(
                {'error': 'scan already running', 'job_id': _scan_state['job_id']},
                status_code=409,
            )
        SCAN_JOBS_DIR.mkdir(parents=True, exist_ok=True)
        already = len(_read_checkpoint(job_id))
        _scan_state.update({
            'running': True, 'job_id': job_id, 'total': len(tickers),
            'completed': already, 'passed': 0, 'excluded_banks': 0,
            'insufficient': 0, 'current_ticker': None, 'done': False, 'error': None,
            'stopped_early': False, 'stop_reason': None,
        })
        # Recount stats from checkpoint so resume shows correct running totals
        for row in _read_checkpoint(job_id).values():
            if row['status'] in ('green', 'yellow'):
                _scan_state['passed'] += 1
            elif row['status'] == 'excluded_bank':
                _scan_state['excluded_banks'] += 1
            elif row['status'] == 'insufficient':
                _scan_state['insufficient'] += 1
        _scan_maps['sector'] = sector_map
        _scan_maps['company'] = company_map
        _scan_maps['mcap'] = mcap_map
    threading.Thread(target=_scan_worker, args=(job_id, tickers), daemon=True).start()
    return JSONResponse({'job_id': job_id, 'total': len(tickers),
                         'resumed_from': already, 'running': True})


@app.get("/api/scan/status")
async def scan_status():
    with _scan_lock:
        state = dict(_scan_state)
    winners = []
    excluded = []
    if state['job_id']:
        for t, row in _read_checkpoint(state['job_id']).items():
            if row['status'] in ('green', 'yellow'):
                winners.append({
                    'ticker': t,
                    'company': _scan_maps['company'].get(t, '') or t,
                    'sector': _scan_maps['sector'].get(t, 'Unknown'),
                    'mcap': _scan_maps['mcap'].get(t, 'N/A'),
                    'eps': [0, 0, 0],
                    'rev': [float(x) for x in row['rev_yoy'].split(';')] if row['rev_yoy'] else [0, 0, 0],
                    'margin': [float(x) for x in row['margin'].split(';')] if row['margin'] else [0, 0, 0],
                    'status': row['status'],
                })
            elif row['status'] == 'excluded_bank':
                excluded.append(t)
    # Failure-reason tally so a partial/stopped run is diagnosable from the
    # status payload alone, without opening the checkpoint CSV.
    reason_counts = {}
    if state['job_id']:
        for row in _read_checkpoint(state['job_id']).values():
            r = (row.get('reason') or '').strip()
            if r:
                reason_counts[r] = reason_counts.get(r, 0) + 1

    return JSONResponse({
        'running': state['running'], 'done': state['done'], 'error': state['error'],
        'stopped_early': state['stopped_early'], 'stop_reason': state['stop_reason'],
        'total': state['total'], 'completed': state['completed'],
        'current_ticker': state['current_ticker'],
        'winners': winners,
        'excluded_banks': excluded,
        'failure_reasons': reason_counts,
        'meta': {
            'total': state['total'],
            'passed': len(winners),
            'insufficient': state['insufficient'],
            'excluded_banks': len(excluded),
        },
    })

@app.get("/api/ticker/{ticker}")
async def ticker_data(ticker: str):
    t = ticker.upper()
    now = time.time()
    evict_cache()
    
    if t in TICKER_CACHE:
        cached, ts = TICKER_CACHE[t]
        if now - ts < CACHE_TTL:
            return JSONResponse(cached)
    
    try:
        # Offloaded so the event loop stays free; the adapter's global lock
        # still guarantees only one pipeline call runs at a time server-wide.
        data = await run_in_threadpool(get_code33_data, t, CACHE_VERSION)
        if not data:
            return JSONResponse({'error': 'No data'},
                                status_code=404)
        
        data['status'] = data.get('status', 'insufficient')
        

        # Yahoo uses SEC's hyphen form for share classes (BRK-B, not BRK.B) —
        # the same normalization the engine already applies via
        # normalize_ticker(). Passing the raw dotted ticker returned empty
        # metadata, which made fast_info raise and 500'd the whole endpoint.
        sym = normalize_ticker(t)
        tk = yf.Ticker(sym)

        info = tk.fast_info  # chart-API backed: no crumb, unaffected by the fault below
        try:
            # .info is crumb-authenticated like the holders call, so it goes
            # through the same stale-crumb retry — without it, company_name
            # silently fell back to the raw ticker and pe_ratio to 'N/A'.
            full_info, _retried = _yf_quote_summary(
                sym, lambda x: x.info or {}, is_empty=_info_is_empty)
        except Exception as e:
            print(f"[ticker] {t} .info failed: {type(e).__name__}: {e}")
            full_info = {}

        def fi(attr, default=None):
            """fast_info is a lazy dict that raises KeyError (e.g.
            'exchangeTimezoneName') when Yahoo returns no metadata for a
            symbol. getattr's default only absorbs AttributeError, so that
            KeyError escaped and became a 500. Degrade to the default instead —
            a missing quote should cost one field, not the whole response."""
            try:
                return getattr(info, attr, default)
            except Exception:
                return default

        data['price'] = fi('last_price', 0)
        data['company_name'] = full_info.get(
            'shortName', t)

        data['change'] = fi('last_price', 0) - \
          fi('regular_market_previous_close',
          fi('previous_close', 0))

        data['change_pct'] = (data['change'] /
          fi('regular_market_previous_close',
          fi('previous_close', 1))) * 100

        mc = fi('market_cap', None)
        if mc is None:
            mc = full_info.get('marketCap', 0)
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"{v/1e12:.1f}T"
                if v >= 1e9:  return f"{v/1e9:.1f}B"
                if v >= 1e6:  return f"{v/1e6:.1f}M"
                return f"{v:,.0f}"
            except: return "N/A"
        data['market_cap_fmt'] = fmt_mcap(mc)
        
        data['pe_ratio'] = full_info.get(
            'trailingPE', 'N/A')

        data['week52_high'] = fi('year_high', 0)
        data['week52_low'] = fi('year_low', 0)
        data['avg_volume'] = fi('three_month_average_volume', 0)
        
        import logging
        logging.warning(f"DATA KEYS: {list(data.keys())}")
        
        TICKER_CACHE[t] = (data, now)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/chart/{ticker}")
async def chart_data(ticker: str, period: str = "3mo", interval: str = "1d"):
    t = ticker.upper()
    cache_key = f"chart_{t}_{period}_{interval}"
    now = time.time()
    evict_cache()
    
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < CACHE_TTL_CHART:
            return JSONResponse(cached)
    
    try:
        # normalize_ticker(): Yahoo uses SEC's hyphen form (BRK-B), not the dot
        # notation (BRK.B) the rest of the app carries. Un-normalized, this
        # returned an empty history and the handler 404'd with "No data".
        hist = yf.Ticker(normalize_ticker(t)).history(period=period, interval=interval)
        if hist.empty:
            return JSONResponse({'error': 'No data'}, 
                                status_code=404)
        
        prices = [
            {
                'date': str(idx.date()),
                'close': round(float(row['Close']), 2)
            }
            for idx, row in hist.iterrows()
        ]
        
        result = {'ticker': t, 'period': period, 
                  'prices': prices}
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/financials/{ticker}")
async def financials(ticker: str):
    import numpy as np
    t = ticker.upper()
    cache_key = f"fin_{t}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < CACHE_TTL_FINANCIALS:
            return JSONResponse(cached)
    try:
        # normalize_ticker(): un-normalized, Yahoo returned nothing for dot
        # tickers, so balance_sheet/cash_flow/valuation all came back empty
        # while the engine-sourced 'earnings' array (already normalized) was fine.
        tk = yf.Ticker(normalize_ticker(t))
        def df_to_dict(df):
            if df is None or df.empty:
                return {}
            df = df.copy()
            result = {}
            for idx in df.index:
                row = {}
                for col in df.columns:
                    val = df.loc[idx, col]
                    if hasattr(val, 'item'):
                        val = val.item()
                    if val is None or (
                        isinstance(val, float) and 
                        np.isnan(val)):
                        val = None
                    row[str(col.date() if hasattr(
                        col, 'date') else col)] = val
                result[str(idx)] = row
            return result
        
        def fmt_val(v):
            if v is None: return None
            try:
                v = float(v)
                if abs(v) >= 1e9:
                    return f"{v/1e9:.2f}B"
                if abs(v) >= 1e6:
                    return f"{v/1e6:.0f}M"
                return f"{v:.2f}"
            except: return None
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            f_inc = executor.submit(lambda: tk.quarterly_income_stmt)
            f_bal = executor.submit(lambda: tk.quarterly_balance_sheet)
            f_cf  = executor.submit(lambda: tk.quarterly_cashflow)
            f_info = executor.submit(lambda: tk.info)
            f_cal = executor.submit(lambda: tk.calendar)

            inc = f_inc.result()
            bal = f_bal.result()
            cf  = f_cf.result()
            # .info is the only crumb-backed call in this group that RAISES on a
            # stale crumb (TypeError out of yfinance's own parser, confirmed by
            # probe: income/balance/cashflow/calendar all degrade quietly). Left
            # unguarded it escaped the whole handler, so a crumb fault cost the
            # balance sheet and cash flow too, not just the valuation block.
            try:
                info = f_info.result() or {}
            except Exception as e:
                print(f"[financials] {t} .info fetch failed: {type(e).__name__}: {e}")
                info = {}
            cal_data = f_cal.result()

        # .info feeds the whole valuation block below and is crumb-authenticated;
        # a stale crumb returned {} here and every ratio rendered as null.
        if _info_is_empty(info):
            try:
                info, _retried = _yf_quote_summary(
                    normalize_ticker(t), lambda x: x.info or {}, is_empty=_info_is_empty)
            except Exception as e:
                print(f"[financials] {t} .info retry failed: {type(e).__name__}: {e}")
                info = info or {}

        # --- Build earnings list from secfsdstools + yfinance merge ---
        earnings_list = []

        try:
            yf_df = inc  # already fetched above

            # EPS from yfinance — up to 5 quarters
            yf_eps = {}
            if yf_df is not None and not yf_df.empty:
                for col in yf_df.columns:
                    eps_val = None
                    for field in ['Diluted EPS', 'DilutedEPS', 'Basic EPS', 'BasicEPS']:
                        if field in yf_df.index:
                            v = yf_df.loc[field, col]
                            if v is not None and str(v) != 'nan':
                                try:
                                    eps_val = float(v)
                                    break
                                except (TypeError, ValueError):
                                    pass
                    date_str = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)[:10]
                    yf_eps[date_str] = eps_val

            # Revenue + net margin from get_code33_data() — date-aware gap
            # detection (real filed dates, correct edgartools coverage for
            # the newest quarter). n_quarters=12: 8 display quarters + 4
            # buffer for this endpoint's own index-based margin/EPS YoY below.
            c33_rev_by_date = {}
            c33_rev_yoy_by_date = {}
            c33_margin_by_date = {}
            try:
                c33 = await run_in_threadpool(get_code33_data, t, CACHE_VERSION, 12)
                rev_dates = c33.get('rev_end_dates') or []
                rev_vals = c33.get('rev') or []
                rev_yoy_vals = c33.get('rev_yoy') or []
                for d, v in zip(rev_dates, rev_vals):
                    c33_rev_by_date[d] = v
                # rev_yoy is only positionally aligned with rev_end_dates when
                # every target quarter has a value — guard rather than assume.
                if len(rev_yoy_vals) == len(rev_dates):
                    for d, v in zip(rev_dates, rev_yoy_vals):
                        c33_rev_yoy_by_date[d] = v
                npm_dates = c33.get('npm_ends') or []
                npm_vals = c33.get('npm') or []
                for d, v in zip(npm_dates, npm_vals):
                    c33_margin_by_date[d] = v
            except Exception as e:
                print(f"[financials] get_code33_data failed: {e}")

            # get_code33_data's real filed dates and yfinance's own
            # calendar-normalized quarter dates rarely match exactly (e.g.
            # NVDA's real 2026-04-26 vs yfinance's 2026-04-30) — match by
            # proximity, not exact string equality, or the same quarter
            # splits into two incomplete rows instead of one complete one.
            def _closest_date(target_str, candidates, tolerance_days=10):
                try:
                    target = datetime.strptime(target_str, '%Y-%m-%d').date()
                except Exception:
                    return None
                best, best_diff = None, tolerance_days + 1
                for c in candidates:
                    try:
                        diff = abs((datetime.strptime(c, '%Y-%m-%d').date() - target).days)
                    except Exception:
                        continue
                    if diff <= tolerance_days and diff < best_diff:
                        best, best_diff = c, diff
                return best

            # Collect all unique dates: c33's real filed dates are
            # authoritative; only pull in a yfinance date if nothing in c33
            # is close to it (keeps any EPS-only history c33 doesn't cover).
            c33_dates = set(c33_rev_by_date.keys()) | set(c33_margin_by_date.keys())
            eps_keys = list(yf_eps.keys())
            unmatched_eps_dates = {
                ek for ek in eps_keys if _closest_date(ek, c33_dates) is None
            }
            all_dates = sorted(c33_dates | unmatched_eps_dates, reverse=True)[:12]

            # Build merged quarters
            raw_quarters = []
            for d in all_dates:
                rev = c33_rev_by_date.get(d)
                margin = c33_margin_by_date.get(d)
                eps_key = _closest_date(d, eps_keys)
                eps = yf_eps.get(eps_key) if eps_key else None
                raw_quarters.append({
                    'date': d,
                    'revenue': rev,
                    'rev_yoy': c33_rev_yoy_by_date.get(d),
                    'net_margin': margin,
                    'net_margin_yoy': None,
                    'eps': eps,
                    'eps_yoy': None,
                })

            # Calculate YoY fields (compare index i vs i+4) — margin/EPS only.
            # Revenue YoY comes pre-computed from get_code33_data above
            # (fiscal-period-matched, not this naive index lookback).
            for i, q in enumerate(raw_quarters):
                if i + 4 < len(raw_quarters):
                    prev_m = raw_quarters[i+4].get('net_margin')
                    curr_m = q.get('net_margin')
                    if curr_m is not None and prev_m is not None:
                        q['net_margin_yoy'] = curr_m - prev_m

                    prev_eps = raw_quarters[i+4].get('eps')
                    curr_eps = q.get('eps')
                    if curr_eps is not None and prev_eps is not None and prev_eps != 0:
                        q['eps_yoy'] = (curr_eps - prev_eps) / abs(prev_eps) * 100

            earnings_list = raw_quarters

        except Exception as e:
            print(f"[financials] earnings build failed: {e}")
            earnings_list = []

        # First 8 for display — rest only needed for YoY calculation
        earnings_list = earnings_list[:8]

        next_earnings = None
        try:
            cal = cal_data
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                ed = cal['Earnings Date']
                if isinstance(ed, list) and len(ed) > 0:
                    next_earnings = str(ed[0])
            elif hasattr(cal, 'iloc') and 'Earnings Date' in cal.index:
                val = cal.loc['Earnings Date']
                if hasattr(val, 'iloc'): val = val.iloc[0]
                next_earnings = str(val.date() if hasattr(val, 'date') else val).split(' ')[0]
        except: pass
        
        result = {
            'balance_sheet': df_to_dict(bal),
            'cash_flow': df_to_dict(cf),
            'valuation': {
                'P/E ratio': info.get('trailingPE'),
                'Forward P/E': info.get('forwardPE'),
                'P/S ratio': info.get('priceToSalesTrailing12Months'),
                'P/B ratio': info.get('priceToBook'),
                'EV/EBITDA': info.get('enterpriseToEbitda'),
                'EV/Revenue': info.get('enterpriseToRevenue'),
                'Debt/Equity': info.get('debtToEquity'),
                'ROE': info.get('returnOnEquity'),
                'ROA': info.get('returnOnAssets'),
                'Profit margin': info.get('profitMargins'),
            },
            'earnings': earnings_list,
            'next_earnings': next_earnings
        }
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)})

@app.get("/api/news/{ticker}")
async def news(ticker: str):
    t = ticker.upper()
    cache_key = f"news_{t}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < CACHE_TTL_NEWS:
            return JSONResponse(cached)

    items = []
    seen_titles = set()

    # Source 1: SeekingAlpha via FinNews — fastest (0.42s), ticker-specific, analyst quality
    try:
        import FinNews as fn
        sa = fn.SeekingAlpha(topics=[f'${t}'])
        sa_news = sa.get_news() or []
        for a in sa_news[:15]:
            title = a.get('title', '').strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            pub = a.get('published', '')
            items.append({
                'title': title,
                'source': 'Seeking Alpha',
                'url': a.get('link', '') or a.get('url', ''),
                'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                'ts': _parse_rfc2822(pub),
            })
    except Exception as e:
        print(f"[news] SeekingAlpha failed: {e}")

    # Source 2: tradingview-scraper — ticker-specific, Dow Jones/Barron's/MarketWatch
    try:
        from tradingview_scraper.symbols.news import NewsScraper
        ns = NewsScraper()
        articles = ns.scrape_headlines(symbol=t, exchange='NASDAQ', sort='latest')
        if not isinstance(articles, list):
            articles = articles.get('data', [])
        for a in articles[:15]:
            title = a.get('title', '').strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            url = a.get('link', '')
            if not url and a.get('storyPath'):
                url = 'https://www.tradingview.com' + a['storyPath']
            pub = a.get('published', 0)
            items.append({
                'title': title,
                'source': a.get('source', a.get('provider', '')),
                'url': url,
                'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                'ts': pub if isinstance(pub, (int, float)) else 0,
            })
    except Exception as e:
        print(f"[news] tradingview-scraper failed: {e}")

    # Source 3: yfinance fallback — only if both above return nothing
    if not items:
        try:
            # normalize_ticker(): defensive. This fallback only runs when both
            # earlier sources return nothing, so the dot-ticker fault was never
            # observed here (BRK.B news resolves via tradingview-scraper), but
            # the call site carried the same latent bug.
            tk = yf.Ticker(normalize_ticker(t))
            for n in (tk.news or [])[:12]:
                c = n.get('content', {})
                title = (c.get('title', '') or n.get('title', '')).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                pub = c.get('pubDate', '') or n.get('providerPublishTime', 0)
                items.append({
                    'title': title,
                    'source': c.get('provider', {}).get('displayName', '') or n.get('publisher', ''),
                    'url': c.get('canonicalUrl', {}).get('url', '') or n.get('link', ''),
                    'time': _parse_rfc2822(pub) if isinstance(pub, str) else (int(pub) if isinstance(pub, (int, float)) and pub > 0 else 0),
                    'ts': pub if isinstance(pub, (int, float)) else 0,
                })
        except Exception as e:
            print(f"[news] yfinance fallback failed: {e}")

    # Sort all items newest first
    items.sort(key=lambda x: x.get('ts', 0), reverse=True)

    # Strip internal ts field before returning
    result = {
        'news': [
            {'title': i['title'], 'source': i['source'], 'url': i['url'], 'time': i['ts']}
            for i in items
        ]
    }
    TICKER_CACHE[cache_key] = (result, now)
    return JSONResponse(result)


def _fmt_news_time(val):
    try:
        from datetime import datetime
        if isinstance(val, (int, float)) and val > 0:
            dt = datetime.utcfromtimestamp(val)
        elif isinstance(val, str) and val:
            import email.utils
            parsed = email.utils.parsedate_to_datetime(val)
            dt = parsed.replace(tzinfo=None)
        else:
            return ''
        diff = datetime.utcnow() - dt
        mins = int(diff.total_seconds() / 60)
        if mins < 0: return 'just now'
        if mins < 60: return f"{mins}m ago"
        if mins < 1440: return f"{mins//60}h ago"
        return f"{mins//1440}d ago"
    except:
        return ''


def _parse_rfc2822(val):
    try:
        import email.utils
        parsed = email.utils.parsedate_to_datetime(val)
        return int(parsed.timestamp())
    except:
        return 0


@app.get("/api/ownership/{ticker}")
async def ownership(ticker: str):
    from datetime import datetime

    def num(v, default=0.0):
        """NaN-safe float. Yahoo leaves pctHeld/Value as NaN on real rows
        (confirmed on AAPL: two of its three newest insider transactions carry
        Value=NaN). float('nan') is not JSON-compliant, so JSONResponse raised
        ValueError and the handler's except returned an empty payload — the
        same visible symptom as the stale crumb, an independent second cause."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        return f if math.isfinite(f) else default

    def fmt_date(d):
        try:
            if isinstance(d, str):
                dt = datetime.strptime(d.split(' ')[0], '%Y-%m-%d')
            else:
                dt = pd.Timestamp(d).to_pydatetime()
            return dt.strftime('%b %d')
        except:
            return str(d)

    cache_key = f"own_{ticker.upper()}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < CACHE_TTL_OWNERSHIP:
            return JSONResponse(cached)

    try:
        # normalize_ticker(): confirmed at the yfinance layer that BRK-B returns
        # 10 institutional + 36 insider rows while BRK.B returns an empty frame.
        #
        # _yf_quote_summary(): this endpoint used to return empty for EVERY
        # ticker on a long-running server while succeeding in a fresh process —
        # a stale process-wide crumb, see the notes on _yf_force_fresh_crumb().
        # Both frames empty is the signal: a real company has institutional
        # holders, insider transactions, or both.
        sym = normalize_ticker(ticker.upper())
        (holders, insiders), _retried = _yf_quote_summary(
            sym,
            lambda tk: (tk.institutional_holders, tk.insider_transactions),
            is_empty=lambda frames: all(
                f is None or getattr(f, 'empty', True) for f in frames
            ),
        )

        inst_list = []
        if holders is not None and not holders.empty:
            for _, row in holders.head(5).iterrows():
                pct = num(row.get('pctHeld',
                      row.get('% Out', 0))) * 100
                inst_list.append({
                    'name': str(row.get('Holder', 
                            row.get('Name', ''))),
                    'pct': round(pct, 1)
                })
        
        insider_list = []
        if insiders is not None and not insiders.empty:
            for _, row in insiders.head(3).iterrows():
                val = num(row.get('Value', 0))
                insider_list.append({
                    'name': str(row.get('Insider', '')),
                    'role': str(row.get('Relationship', '')),
                    'date': fmt_date(row.get('Start Date', '')),
                    'value': val,
                    'type': 'BUY' if val > 0 else 'SELL'
                })
        
        result = {
            'institutional': inst_list,
            'insiders': insider_list
        }
        # Only cache a payload that actually carries data. An empty result is
        # ambiguous — a company with no 13F/Form 4 rows looks identical to a
        # transient Yahoo failure, and pinning a failure for 10 minutes is the
        # bug class this endpoint was already caught by once.
        if inst_list or insider_list:
            TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        # Still degrades to an empty payload rather than a 500 — but says so in
        # the log now. The previous bare `except` returned this shape with no
        # trace at all, which is what hid the stale-crumb fault for so long.
        print(f"[ownership] {ticker.upper()} failed: {type(e).__name__}: {e}")
        return JSONResponse({
            'institutional': [],
            'insiders': []
        })

@app.get("/api/peers/{ticker}")
async def peers(ticker: str):
    from utils.code33_adapter import get_code33_data, CACHE_VERSION

    cache_key = f"peers_{ticker.upper()}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < CACHE_TTL_PEERS:
            return JSONResponse(cached)

    try:
        # normalize_ticker(): un-normalized, .info came back without a 'sector',
        # so SECTOR_PEERS.get('') returned [] and dot tickers got an empty peer list.
        _yf_sym = normalize_ticker(ticker.upper())
        # .info is crumb-authenticated: when it came back empty there was no
        # 'sector', SECTOR_PEERS.get('') returned [], and the peer list was
        # empty for reasons that had nothing to do with the ticker.
        info, _retried = _yf_quote_summary(
            _yf_sym, lambda x: x.info or {}, is_empty=_info_is_empty)
        # Get peers from recommendationKey or sector peers
        # Use analyst recommendations to find peer tickers
        recs = yf.Ticker(_yf_sym).recommendations
        # Get sector and find similar companies
        sector = info.get('sector', '')
        
        # Hardcode peers per sector as fallback
        SECTOR_PEERS = {
            'Technology': ['NVDA','MSFT','AAPL','GOOGL','META'],
            'Health Technology': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Healthcare': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Consumer Cyclical': ['AMZN','TSLA','HD','MCD','NKE'],
            'Financial Services': ['JPM','BAC','GS','MS','V'],
            'Energy': ['XOM','CVX','COP','SLB','EOG'],
            'Industrials': ['CAT','DE','HON','UPS','LMT'],
            'Communication Services': ['META','GOOGL','NFLX','DIS','CMCSA'],
        }
        
        peer_tickers = SECTOR_PEERS.get(sector, [])
        # Remove self
        peer_tickers = [p for p in peer_tickers 
                       if p != ticker.upper()][:4]
        
        peers_data = []
        for p in peer_tickers:
            try:
                d = await run_in_threadpool(get_code33_data, p, CACHE_VERSION)
                if not d:
                    continue
                last_eps = next((x for x in reversed(
                    d.get('eps_yoy', []) or []) 
                    if x is not None), None)
                last_rev = next((x for x in reversed(
                    d.get('rev_yoy', []) or []) 
                    if x is not None), None)
                last_npm = next((x for x in reversed(
                    d.get('npm', []) or []) 
                    if x is not None), None)
                peers_data.append({
                    'ticker': p,
                    'eps_yoy': round(last_eps, 1) 
                               if last_eps is not None else None,
                    'rev_yoy': round(last_rev, 1) 
                               if last_rev is not None else None,
                    'npm': round(last_npm, 1) 
                           if last_npm is not None else None,
                    'status': d.get('status', '')
                })
            except:
                continue
        
        result = {
            'ticker': ticker.upper(),
            'peers': peers_data
        }
        # Cache on a resolved .info, not on a non-empty peer list: a sector
        # that simply isn't in SECTOR_PEERS (Consumer Defensive, Utilities...)
        # legitimately yields [], and that answer is worth caching too. What
        # must NOT be cached is [] caused by .info failing, which is exactly
        # what _info_is_empty() distinguishes.
        if not _info_is_empty(info):
            TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({
            'ticker': ticker.upper(),
            'peers': [],
            'error': str(e)
        })




# ---------------------------------------------------------------------------
# News Scanner (Stage 1) — additive, isolated
# ---------------------------------------------------------------------------
# Registered last and deliberately kept to three lines here. The feature owns
# its own module, its own store, its own lock and its own daemon thread; it
# shares no route prefix, no cache and no dependency with anything above,
# including /api/news, which is a separate feature and is not touched by it.
# Imported at the bottom so news_scanner's own lazy `from api import server`
# (it reads _scan_state to back off during a Code 33 scan) always finds this
# module fully defined. The poller itself is started from _lifespan above, not
# here — see that docstring for why import time was wrong.
from api.news_scanner import router as news_scanner_router

app.include_router(news_scanner_router)
