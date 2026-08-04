"""News Scanner — Stage 1: core feed, headlines only.

Deliberately isolated from everything else in this app:

  - It never calls get_code33_data(), so it never touches the adapter's global
    _PIPELINE_LOCK. Nothing here can slow a scan down or be slowed by one.
  - It does not share TICKER_CACHE. That dict has no lock and is written only
    from request handlers today; a background writer would introduce genuine
    concurrent mutation against evict_cache()'s iteration. This module keeps its
    own store behind its own lock.
  - It is a separate universe from /api/news (the ticker-scoped, on-demand feed
    on the analysis page). No code, route or dependency is shared with it.

The poller runs on a daemon thread, NOT an asyncio task. api/server.py's
/api/financials submits to a ThreadPoolExecutor and then calls .result()
synchronously inside an `async def`, which blocks the single event loop for the
full duration of that fetch. An asyncio poller would stall every time someone
loads financials; a thread does not. This mirrors _scan_worker's pattern.

Robustness principle: every source is fetched inside its own try/except, logs
its own failure, and leaves the rest of the feed intact. A source that fails
contributes nothing — it never blanks what the other source already collected.
That is the /api/ownership lesson: a silently swallowed failure is worse than a
visibly partial one, so per-source state is reported at /api/news-scanner/status
rather than hidden.

NOT in this stage, on purpose: catalyst tagging (Stage 2), full article text
(Stage 3), wire RSS and cross-source dedup (Stage 4).
"""
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Reuse the project's single set_identity() call rather than declaring a second
# identity. Importing code33.edgar_fill is what executes it (edgar_fill.py:21);
# edgartools stores the result in the EDGAR_IDENTITY env var, and get_identity()
# reads it back. SEC's rate budget is per-identity, which is precisely why this
# must not become a second one — the Code 33 pipeline already spends that budget.
import code33.edgar_fill  # noqa: F401  — imported for its set_identity() side effect
from edgar import get_identity

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "news_session.db"

ET = ZoneInfo("America/New_York")

router = APIRouter()


# ---------------------------------------------------------------------------
# Polling cadence
# ---------------------------------------------------------------------------
# EDGAR's current-events feed surfaces a filing within a couple of minutes of
# acceptance — the ~10 minute figure people quote is the DAILY INDEX, a
# different artifact. One request every 120s is 0.008 req/s against SEC's 10
# req/s budget, so freshness here is free.
EDGAR_INTERVAL = 120
# ...except that budget is shared with the Code 33 pipeline, which during a full
# scan hammers EDGAR for hours. While a scan is running this backs off. The cost
# of being 3 minutes stale on a Sunday-afternoon scan is nothing; the cost of
# competing with the scan for SEC budget is a scan that slows or trips a limit.
EDGAR_INTERVAL_DURING_SCAN = 300

# 1 call/min against Finnhub's free-tier 60/min cap = 1.7% of it. The general
# feed does not update faster than this, so a shorter interval buys nothing.
FINNHUB_GENERAL_INTERVAL = 60

# Watchlist company-news is BREADTH, not speed — Finnhub's per-company feed is
# near-daily in granularity, so the fast lane for a watchlist name is EDGAR, not
# this. Each ticker refreshes every 300s, staggered so the calls spread across
# the window instead of bursting. A 50-name watchlist at 60s would be 50
# calls/min — 83% of the cap, one burst from being throttled. At 300s it
# averages ~10/min.
FINNHUB_COMPANY_INTERVAL = 300
# Hard ceiling regardless of watchlist size. Leaves 50% of the free tier
# permanently unused as headroom.
FINNHUB_MAX_CALLS_PER_MIN = 30

# Market-hours window, ET, weekdays. Wider than 09:30-16:00 on purpose: earnings
# and 8-Ks cluster in pre-market (from ~07:00) and after the close (to ~20:00),
# which is exactly the news this tab exists to catch. Outside it the poller
# idles — no calls to either source.
MARKET_OPEN_HOUR = 7
MARKET_CLOSE_HOUR = 20

POLL_TICK = 5  # loop granularity; each source has its own next-due timestamp

EDGAR_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
    "&company=&dateb=&owner=include&start=0&count=100&output=atom"
)

FEED_MEMORY_LIMIT = 500  # in-memory ring; SQLite holds the full session


# ---------------------------------------------------------------------------
# Store — in-memory feed + per-source health, both behind one lock
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_FEED = []          # newest-first, capped at FEED_MEMORY_LIMIT
_SEEN = set()       # item ids already in _FEED, so a re-poll doesn't duplicate
_SOURCES = {
    "edgar": {"last_ok": None, "last_error": None, "last_attempt": None, "items": 0},
    "finnhub_general": {"last_ok": None, "last_error": None, "last_attempt": None, "items": 0},
    "finnhub_company": {"last_ok": None, "last_error": None, "last_attempt": None, "items": 0},
}
_POLLER_STARTED = False
_POLLER_STATE = {"running": False, "in_window": False, "primed": False}


# finnhub-python passes the API key as a URL query parameter, so any exception
# carrying the request URL — a timeout, a 502, a DNS failure — embeds the live
# key in its message. Logging `{e}` verbatim therefore wrote the secret to the
# server log in plaintext (observed, not theorised). Redaction is applied at the
# single choke point every message passes through, so no future call site can
# reintroduce the leak by forgetting to sanitise.
_SECRET_RE = re.compile(r"(token|api[_-]?key|apikey)=([^&\s'\"]+)", re.IGNORECASE)


def _redact(msg):
    return _SECRET_RE.sub(r"\1=<redacted>", str(msg))


def _log(msg):
    print(f"[news-scanner] {_redact(msg)}", flush=True)


# ---------------------------------------------------------------------------
# Session day — calendar day in ET, not process lifetime
# ---------------------------------------------------------------------------
# Process lifetime would be wrong here: uvicorn runs with --reload, so editing
# any file in the repo restarts the worker. Tying "session" to the process would
# mean an unrelated edit at 11am silently discards the morning's history.
def _session_date():
    return datetime.now(ET).strftime("%Y-%m-%d")


def _in_market_window(now=None):
    now = now or datetime.now(ET)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


# ---------------------------------------------------------------------------
# SQLite — session history
# ---------------------------------------------------------------------------
# WAL because the poller thread writes while request threads read, and because
# --reload can kill the process mid-write; WAL recovers from that cleanly where
# the default rollback journal is more likely to leave a stale lock behind.
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_items (
                id           TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                source       TEXT NOT NULL,
                ticker       TEXT,
                company      TEXT,
                headline     TEXT NOT NULL,
                url          TEXT,
                published    REAL,
                first_seen   REAL,
                meta         TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_session ON news_items(session_date, published DESC)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker   TEXT PRIMARY KEY,
                added_at REAL NOT NULL
            )
        """)
        conn.commit()


_last_purged_for = None
_purge_lock = threading.Lock()


def _purge_if_new_day():
    """Session history is TODAY only. Cleared on the first request/poll of a new
    calendar day rather than on a timer, so a server that was asleep at midnight
    still starts the day clean."""
    global _last_purged_for
    today = _session_date()
    with _purge_lock:
        if _last_purged_for == today:
            return
        try:
            with _connect() as conn:
                cur = conn.execute("DELETE FROM news_items WHERE session_date != ?", (today,))
                conn.commit()
                if cur.rowcount:
                    _log(f"session rollover -> {today}: purged {cur.rowcount} stale rows")
            _last_purged_for = today
        except Exception as e:
            _log(f"purge failed (non-fatal): {e}")


def _persist(items):
    if not items:
        return
    today = _session_date()
    try:
        with _connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO news_items
                   (id, session_date, source, ticker, company, headline, url,
                    published, first_seen, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(i["id"], today, i["source"], i.get("ticker"), i.get("company"),
                  i["headline"], i.get("url"), i.get("published"), i["first_seen"],
                  json.dumps(i.get("meta") or {})) for i in items],
            )
            conn.commit()
    except Exception as e:
        # A history write failing must not cost the live feed — the item is
        # already in _FEED and will still render.
        _log(f"persist failed (non-fatal, {len(items)} items): {e}")


# ---------------------------------------------------------------------------
# Whole-market universe — SEC's own ticker map, already on disk
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _cik_to_ticker():
    """CIK -> ticker, from data/company_tickers.json (10,432 symbols). This is
    what makes 'whole market' mean every US-listed filer rather than the ~540
    of the Code 33 universe. Loaded once per process."""
    path = DATA_DIR / "company_tickers.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {int(v["cik_str"]): v["ticker"] for v in raw.values()}
    except Exception as e:
        _log(f"ticker map unavailable, EDGAR items will carry no ticker: {e}")
        return {}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
class _TokenBucket:
    """Calls-per-minute ceiling, enforced by the caller blocking until a token
    frees up. Used for Finnhub company-news, where watchlist size is the thing
    that could otherwise walk the call rate into the free-tier cap."""

    def __init__(self, capacity_per_min):
        self.capacity = capacity_per_min
        self._calls = []
        self._lock = threading.Lock()

    def take(self, timeout=30):
        deadline = time.time() + timeout
        while True:
            with self._lock:
                now = time.time()
                self._calls = [t for t in self._calls if now - t < 60]
                if len(self._calls) < self.capacity:
                    self._calls.append(now)
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(0.5)


_finnhub_bucket = _TokenBucket(FINNHUB_MAX_CALLS_PER_MIN)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
_EDGAR_TITLE_RE = re.compile(r"^(?P<form>[\w/-]+)\s*-\s*(?P<company>.*?)\s*\((?P<cik>\d{10})\)")
_EDGAR_ACCNO_RE = re.compile(r"AccNo:</b>\s*([\d-]+)")


def _fetch_edgar():
    """SEC 8-K current-events feed. Headlines only at this stage: the atom
    payload already carries company, CIK, accession and filing time, so nothing
    here fetches the filing document itself. (Document fetching — and the 2/s cap
    that goes with it — belongs to Stage 3, where article text is actually
    read; implementing the cap now would be code with nothing to limit.)"""
    import feedparser

    d = feedparser.parse(EDGAR_FEED_URL, agent=get_identity())
    # feedparser never raises on a bad response; it reports. Treat a non-200 or
    # a parse failure with no entries as an error rather than as "no news".
    status = d.get("status")
    if status and status != 200:
        raise RuntimeError(f"HTTP {status}")
    if d.get("bozo") and not d.entries:
        raise RuntimeError(f"feed parse failed: {d.get('bozo_exception')}")

    cik_map = _cik_to_ticker()
    out = []
    for e in d.entries:
        title = (e.get("title") or "").strip()
        m = _EDGAR_TITLE_RE.match(title)
        if not m:
            continue
        summary = e.get("summary") or ""
        acc = _EDGAR_ACCNO_RE.search(summary)
        accession = acc.group(1) if acc else (e.get("id") or title)
        cik = int(m.group("cik"))
        published = _parse_iso(e.get("updated") or e.get("published"))
        out.append({
            "id": f"edgar:{accession}",
            "source": "SEC EDGAR",
            "ticker": cik_map.get(cik),
            "company": m.group("company"),
            "headline": f"{m.group('form')} — {m.group('company')}",
            "url": e.get("link") or "",
            "published": published,
            "first_seen": time.time(),
            # Raw filing metadata, stored but NOT interpreted at this stage. The
            # 8-K item numbers live in here; mapping them to catalyst types is
            # Stage 2. Kept now only so Stage 2 needs no backfill re-fetch.
            "meta": {"cik": cik, "accession": accession, "form": m.group("form"),
                     "items_raw": _strip_html(summary)},
        })
    return out


def _fetch_finnhub_general():
    """Finnhub free-tier general market news — the whole-market headline feed."""
    client = _finnhub_client()
    rows = client.general_news("general") or []
    out = []
    for n in rows:
        nid = n.get("id")
        headline = (n.get("headline") or "").strip()
        if not headline:
            continue
        related = (n.get("related") or "").strip()
        out.append({
            "id": f"finnhub:{nid}" if nid else f"finnhub:{hash(headline)}",
            "source": n.get("source") or "Finnhub",
            "ticker": related.split(",")[0] if related else None,
            "company": None,
            "headline": headline,
            "url": n.get("url") or "",
            "published": float(n.get("datetime") or 0) or None,
            "first_seen": time.time(),
            "meta": {"category": n.get("category"), "related": related},
        })
    return out


def _fetch_finnhub_company(tickers):
    """Per-ticker Finnhub news for watchlist names, rate-limited by the shared
    bucket. Returns whatever it got — a ticker that fails is skipped, it does
    not abort the batch."""
    if not tickers:
        return []
    client = _finnhub_client()
    today = datetime.now(ET).date()
    frm = (today - timedelta(days=2)).isoformat()
    to = today.isoformat()
    out = []
    for t in tickers:
        if not _finnhub_bucket.take():
            _log(f"finnhub rate ceiling reached, skipping remaining watchlist tickers at {t}")
            break
        try:
            rows = client.company_news(t, _from=frm, to=to) or []
        except Exception as e:
            _log(f"finnhub company_news failed for {t}: {e}")
            continue
        for n in rows[:20]:
            headline = (n.get("headline") or "").strip()
            if not headline:
                continue
            nid = n.get("id")
            out.append({
                "id": f"finnhub:{nid}" if nid else f"finnhub:{t}:{hash(headline)}",
                "source": n.get("source") or "Finnhub",
                "ticker": t,
                "company": None,
                "headline": headline,
                "url": n.get("url") or "",
                "published": float(n.get("datetime") or 0) or None,
                "first_seen": time.time(),
                "meta": {"category": n.get("category"), "related": n.get("related") or t},
            })
    return out


@lru_cache(maxsize=1)
def _finnhub_client():
    from dotenv import load_dotenv
    import finnhub
    # api/server.py never loads .env, so the key is not in the environment
    # unless this does it. Loaded here rather than at import so a missing .env
    # surfaces as a source failure in /status, not an import-time crash that
    # takes the whole app down.
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set in .env")
    return finnhub.Client(api_key=key)


def _strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def _ingest(source_key, items):
    """Merge new items into the in-memory feed and the session DB. Dedup is by
    stable id (accession number for EDGAR, Finnhub's own id), so re-polling the
    same window is idempotent — no MinHash needed until cross-source volume is
    real, which is Stage 4."""
    fresh = []
    with _LOCK:
        for it in items:
            if it["id"] in _SEEN:
                continue
            _SEEN.add(it["id"])
            fresh.append(it)
        if fresh:
            _FEED.extend(fresh)
            _FEED.sort(key=lambda i: (i.get("published") or i["first_seen"]), reverse=True)
            del _FEED[FEED_MEMORY_LIMIT:]
            _SEEN.intersection_update({i["id"] for i in _FEED})
        _SOURCES[source_key]["items"] = len(items)
    _persist(fresh)
    return len(fresh)


def _run_source(source_key, fn, *args):
    """One source, one try/except, one status record. A failure here logs and
    returns — it never propagates far enough to blank the feed the other source
    already filled."""
    _SOURCES[source_key]["last_attempt"] = time.time()
    try:
        items = fn(*args)
        n = _ingest(source_key, items)
        _SOURCES[source_key]["last_ok"] = time.time()
        _SOURCES[source_key]["last_error"] = None
        _log(f"{source_key}: {len(items)} fetched, {n} new")
        return n
    except Exception as e:
        # Redacted here too — last_error is served over HTTP by /status, so an
        # unsanitised message would hand the key to any caller of that endpoint.
        _SOURCES[source_key]["last_error"] = _redact(f"{type(e).__name__}: {e}")
        _log(f"{source_key} FAILED: {type(e).__name__}: {e}")
        return 0


# ---------------------------------------------------------------------------
# Poller
# ---------------------------------------------------------------------------
def _scan_is_running():
    """Read api/server.py's scan state without importing it at module load —
    server.py imports THIS module, so a top-level import would be circular.
    By the time this runs, server is fully imported."""
    try:
        from api import server
        return bool(server._scan_state.get("running"))
    except Exception:
        return False


def _watchlist_tickers():
    try:
        with _connect() as conn:
            return [r["ticker"] for r in conn.execute(
                "SELECT ticker FROM watchlist ORDER BY added_at")]
    except Exception as e:
        _log(f"watchlist read failed: {e}")
        return []


def _poll_loop():
    _POLLER_STATE["running"] = True
    # Prime once at startup regardless of the market window. Without this the
    # tab is empty every evening and all weekend, which makes the feature look
    # broken rather than idle — and makes it unverifiable outside market hours.
    # Ongoing polling still respects the window strictly.
    _log("priming initial fetch (one-off, ignores market window)")
    _run_source("edgar", _fetch_edgar)
    _run_source("finnhub_general", _fetch_finnhub_general)
    _POLLER_STATE["primed"] = True

    next_edgar = time.time() + EDGAR_INTERVAL
    next_general = time.time() + FINNHUB_GENERAL_INTERVAL
    next_company = time.time() + FINNHUB_COMPANY_INTERVAL
    company_cursor = 0

    while True:
        try:
            in_window = _in_market_window()
            _POLLER_STATE["in_window"] = in_window
            now = time.time()
            if in_window:
                if now >= next_edgar:
                    _run_source("edgar", _fetch_edgar)
                    interval = EDGAR_INTERVAL_DURING_SCAN if _scan_is_running() else EDGAR_INTERVAL
                    next_edgar = time.time() + interval
                if now >= next_general:
                    _run_source("finnhub_general", _fetch_finnhub_general)
                    next_general = time.time() + FINNHUB_GENERAL_INTERVAL
                if now >= next_company:
                    wl = _watchlist_tickers()
                    if wl:
                        # Staggered: a slice per tick rather than the whole list
                        # at once, so calls spread across the interval instead
                        # of bursting into the rate ceiling.
                        slice_size = max(1, len(wl) // 5 or 1)
                        batch = wl[company_cursor:company_cursor + slice_size]
                        company_cursor += slice_size
                        if company_cursor >= len(wl):
                            company_cursor = 0
                        _run_source("finnhub_company", _fetch_finnhub_company, batch)
                    next_company = time.time() + max(
                        FINNHUB_COMPANY_INTERVAL // 5, POLL_TICK)
            time.sleep(POLL_TICK)
        except Exception as e:
            # The loop itself must never die — a dead poller is a permanently
            # frozen feed with no visible cause.
            _log(f"poll loop error (continuing): {type(e).__name__}: {e}")
            time.sleep(POLL_TICK)


def _hydrate_from_db():
    """Reload today's items into memory on start.

    Without this a --reload restart would leave the in-memory feed empty until
    the next poll and would re-log every already-stored item as "new". The DB is
    the source of truth for the session precisely so a restart is survivable."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM news_items WHERE session_date = ?"
                " ORDER BY IFNULL(published, first_seen) DESC LIMIT ?",
                (_session_date(), FEED_MEMORY_LIMIT)).fetchall()
        with _LOCK:
            _FEED.clear()
            _SEEN.clear()
            for r in rows:
                d = dict(r)
                try:
                    d["meta"] = json.loads(d.get("meta") or "{}")
                except Exception:
                    d["meta"] = {}
                _FEED.append(d)
                _SEEN.add(d["id"])
        if rows:
            _log(f"hydrated {len(rows)} items from today's session")
    except Exception as e:
        _log(f"hydrate failed (non-fatal, feed will refill on next poll): {e}")


def start_poller():
    global _POLLER_STARTED
    if _POLLER_STARTED:
        return
    _POLLER_STARTED = True
    _init_db()
    _purge_if_new_day()
    _hydrate_from_db()
    threading.Thread(target=_poll_loop, name="news-scanner-poller", daemon=True).start()
    _log(f"poller started (identity={get_identity()})")


# ---------------------------------------------------------------------------
# Routes — all under /api/news-scanner, sharing nothing with /api/news
# ---------------------------------------------------------------------------
@router.get("/api/news-scanner/feed")
async def feed(mode: str = "market", q: str = "", limit: int = 100):
    """mode=market  -> everything collected
       mode=watchlist -> only items whose ticker is on the watchlist
       q -> case-insensitive substring search over headline/company/ticker,
            served from the session DB so it covers the whole day, not just
            what is currently in memory."""
    _purge_if_new_day()
    today = _session_date()

    sql = "SELECT * FROM news_items WHERE session_date = ?"
    params = [today]
    if mode == "watchlist":
        # Filtered in SQL, not in Python after the fact. Filtering the result of
        # a LIMITed query would silently drop watchlist matches whenever the
        # limit was smaller than the unfiltered result set — caught in testing
        # with limit=5, which returned nothing while limit=50 returned a match.
        wl = _watchlist_tickers()
        if not wl:
            return JSONResponse({"mode": mode, "query": q, "session_date": today,
                                 "count": 0, "items": [],
                                 "note": "watchlist is empty"})
        sql += f" AND UPPER(IFNULL(ticker,'')) IN ({','.join('?' * len(wl))})"
        params += [t.upper() for t in wl]
    if q:
        sql += " AND (LOWER(headline) LIKE ? OR LOWER(IFNULL(company,'')) LIKE ?" \
               " OR LOWER(IFNULL(ticker,'')) LIKE ?)"
        needle = f"%{q.lower()}%"
        params += [needle, needle, needle]
    sql += " ORDER BY IFNULL(published, first_seen) DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    try:
        with _connect() as conn:
            rows = [dict(r) for r in conn.execute(sql, params)]
    except Exception as e:
        _log(f"feed query failed: {e}")
        rows = []

    items = []
    for r in rows:
        try:
            r["meta"] = json.loads(r.get("meta") or "{}")
        except Exception:
            r["meta"] = {}
        items.append(r)

    return JSONResponse({
        "mode": mode,
        "query": q,
        "session_date": today,
        "count": len(items),
        "items": items,
    })


@router.get("/api/news-scanner/status")
async def status():
    """Per-source health, deliberately exposed. A source that is failing shows
    its last error here instead of silently contributing nothing."""
    _purge_if_new_day()
    with _LOCK:
        sources = {k: dict(v) for k, v in _SOURCES.items()}
        in_memory = len(_FEED)
    try:
        with _connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) c FROM news_items WHERE session_date = ?",
                (_session_date(),)).fetchone()["c"]
    except Exception:
        total = None
    now_et = datetime.now(ET)
    return JSONResponse({
        "poller_running": _POLLER_STATE["running"],
        "primed": _POLLER_STATE["primed"],
        "in_market_window": _in_market_window(),
        "market_window_et": f"{MARKET_OPEN_HOUR:02d}:00-{MARKET_CLOSE_HOUR:02d}:00 Mon-Fri",
        "now_et": now_et.isoformat(),
        "scan_running": _scan_is_running(),
        "session_date": _session_date(),
        "items_in_memory": in_memory,
        "items_today": total,
        "watchlist_size": len(_watchlist_tickers()),
        "sources": sources,
        "intervals": {
            "edgar": EDGAR_INTERVAL,
            "edgar_during_scan": EDGAR_INTERVAL_DURING_SCAN,
            "finnhub_general": FINNHUB_GENERAL_INTERVAL,
            "finnhub_company": FINNHUB_COMPANY_INTERVAL,
            "finnhub_max_calls_per_min": FINNHUB_MAX_CALLS_PER_MIN,
        },
    })


@router.get("/api/news-scanner/watchlist")
async def watchlist_get():
    return JSONResponse({"tickers": _watchlist_tickers()})


@router.post("/api/news-scanner/watchlist/{ticker}")
async def watchlist_add(ticker: str):
    t = ticker.strip().upper()
    if not t or not re.fullmatch(r"[A-Z0-9.\-]{1,10}", t):
        return JSONResponse({"error": "invalid ticker"}, status_code=400)
    try:
        with _connect() as conn:
            conn.execute("INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?,?)",
                         (t, time.time()))
            conn.commit()
    except Exception as e:
        _log(f"watchlist add failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"tickers": _watchlist_tickers()})


@router.delete("/api/news-scanner/watchlist/{ticker}")
async def watchlist_remove(ticker: str):
    t = ticker.strip().upper()
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE ticker = ?", (t,))
            conn.commit()
    except Exception as e:
        _log(f"watchlist remove failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"tickers": _watchlist_tickers()})
