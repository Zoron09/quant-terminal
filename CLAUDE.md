# QUANT TERMINAL — PROJECT BIBLE
**Location:** `C:\Users\Meet Singh\quant-terminal`
**GitHub:** Zoron09/quant-terminal (branch: main)
**Purpose:** Cinematic stock screening terminal based on Minervini SEPA/Code33 methodology.

---

## ABSOLUTE RULES — READ BEFORE TOUCHING ANYTHING
1. The Code 33 engine lives in the EXTERNAL `code33-screener` project (installed editable
   into `.venv`); `utils/code33_adapter.py` is the only in-repo engine file. NEVER touch
   the `code33-screener` repo from quant-terminal work sessions — engine changes happen
   there, under its own regression suite (`tools/regression_check.py`, 19-ticker baseline).
   (Old rule "never touch utils/code33_engine.py" retired 2026-07-22 — that file and its
   5 helper modules were deleted in the code33-swap branch by explicit owner instruction.)
2. NEVER touch world grid CSS or navigation JS in `frontend/index.html`
3. NEVER use `&&` in PowerShell — use `;` instead
4. ALWAYS use Python patch approach for frontend changes (decode `__bundler/template` JSON → patch → re-encode with `<\/` escaping → write back)
5. ALWAYS inspect exact strings before replacing — never guess
6. ALWAYS run verify script after patching frontend
7. ALWAYS restart server and confirm at localhost:8000 after changes
8. ALWAYS commit and push after any confirmed working change
9. ALWAYS update this CLAUDE.md after any significant change
10. ONE change at a time — test after each
11. If something breaks — STOP, revert to last working git commit, document what happened
12. AFTER EVERY CHANGE — update the CURRENT STATUS section in CLAUDE.md to reflect what was done, then commit CLAUDE.md alongside the changed files in the same commit. No commit is complete without an updated CLAUDE.md.
13. NEVER ask Meet to run a live Wealthsimple login (`tools/wealthsimple_export.py` without a valid cached `tools/session.json`) as a routine verification step. Any change to that script or to `/api/journal/wealthsimple-latest` gets verified with `--dry-run` or the cached session first — real 2FA/credential entry is a rare, deliberate, Meet-initiated action only, never something asked for just to confirm a code change works.
14. ALWAYS reuse the SAME `--start-date` across repeated `tools/wealthsimple_export.py` runs (account inception, or a fixed date picked once) — never a rolling/shifting window. FIFO leg-matching has no state persisted between runs, so a wider or shifted range can pair the same closing leg with a different opener than a prior run did, producing a different `trade_id` for what's economically the same trade. Re-running the *same* range is always safe; this is a usage convention, not something the script validates or blocks.

---

## TECH STACK
- **Backend:** FastAPI — start with `.venv\Scripts\python.exe run.py`
- **Frontend:** Single file `frontend/index.html` (~810KB, Claude Design bundled)
- **Python for scripts:** `C:\Users\Meet Singh\AppData\Local\Programs\Python\Python314\python.exe`
- **Venv Python:** `C:\Users\Meet Singh\quant-terminal\.venv\Scripts\python.exe`
- **Server URL:** `http://localhost:8000` — bound to `127.0.0.1` only as of 2026-07-15 (was `0.0.0.0`).
  **If you've been reaching this app from another device on your LAN (phone, another PC via
  your machine's real IP), that access is now gone** — only this machine can reach it. Change
  `--host` back in `run.py` if that LAN access is actually wanted; this wasn't silently assumed
  to be fine, it's a deliberate tradeoff for the Wealthsimple auto-sync feature below.

---

## DATA SOURCES
| Source | Used For | Location |
|--------|----------|----------|
| secfsdstools | Revenue + Net Margin (primary) | `C:\Users\Meet Singh\secfsdstools\data\` — 426K reports, 69 quarters |
| edgartools | Revenue + Net Margin (targeted gap-fill only) | pip installed |
| yfinance | Chart, price, ownership, peers | pip installed |
| tradingview-scraper | News (primary) | pip installed |
| yfinance | News fallback | pip installed |

---

## FRONTEND ARCHITECTURE
Single file: `frontend/index.html`
The app code lives inside `<script type="__bundler/template">` as JSON-encoded string.
All edits: decode JSON → string replace → re-encode with `<\/` escaping → write back.

**World Grid Layout (DO NOT CHANGE):**
#world { position: absolute; width: 300vw; height: 300vh; top: 0; left: -100vw; }

#page-home     { left: 100vw; top: 0;     } ← center hub

#page-analysis { left: 100vw; top: 100vh; } ← swipe UP from home

#page-screener { left: 0;     top: 0;     } ← swipe LEFT from home

#page-journal  { left: 200vw; top: 0;     } ← swipe RIGHT from home

**Navigation:** `goTo(page)` translates `#world` div. Touch drag `passive: false`. Arrow keys work. DO NOT TOUCH.

---

## DESIGN SYSTEM (locked)
Background:     #000000 (all pages)

Cards:          #141416

Borders:        #2A2A2E

Accent gold:    #D4A843

Positive:       #34D399

Negative:       #F87171

Warning:        #FBBF24

Text primary:   #FAFAFA

Text muted:     #52525B
Fonts: DM Serif Display (headings), Inter (UI), IBM Plex Mono (numbers)

Homepage title: Bodoni Moda 900

---

## BACKEND API ROUTES
All routes in `api/server.py`. DO NOT touch engine files.
GET  /api/ticker/{ticker}          → {price, company_name, change, change_pct, status, market_cap_fmt, pe_ratio, week52_high, week52_low, avg_volume, eps_yoy}

GET  /api/chart/{ticker}?period=1y&interval=1d → {ticker, period, prices: [{date, close}]}

GET  /api/financials/{ticker}      → {earnings: [{date, revenue, rev_yoy, net_margin, net_margin_yoy, eps, eps_yoy}], balance_sheet: {}, cash_flow: {}, valuation: {}}

GET  /api/news/{ticker}            → {news: [{title, source, url, time}]}

GET  /api/ownership/{ticker}       → {institutional: [{name, pct}], insiders: [{name, role, date, value, type}]}

GET  /api/peers/{ticker}           → {ticker, peers: [{ticker, rev_yoy, npm, status}]}

POST /api/scan                     → starts background job: {job_id, total, resumed_from, running} (409 {error, job_id} if one is already running)

GET  /api/scan/status              → {running, done, error, total, completed, current_ticker, winners: [{ticker, company, sector, mcap, eps, rev, margin, status}], excluded_banks: [tickers], meta: {total, passed, insufficient, excluded_banks}}

---

## CURRENT STATUS (update this after every session)

### ✅ WORKING
- Homepage: pure black, Bodoni Moda title, swipe hints, cube animation placeholder
- Navigation: home/analysis/screener still slide (touch + keyboard); journal direction now redirects to `/journal` (real page load) instead of sliding, since the working journal lives outside the `#world` grid — see Journal entry below
- Screener: CSV upload → Code33 scan → GREEN/YELLOW results cards → wired to `/api/scan`
- Journal: separate standalone page at `frontend/journal.html` (sin-list's original file, restyled to quant-terminal's monochrome/white accent + underline tabs, own everything else — not merged into the bundled SPA). `GET /journal` serves it directly; `nav('journal')` in the SPA's bundled `nav()` redirects there (`window.location.href = '/journal'`) instead of sliding the world grid.
- Wealthsimple auto-sync (2026-07-15): `/api/journal/wealthsimple-latest` now also triggers a debounced background refresh (5 min minimum between attempts, single-worker `ThreadPoolExecutor`, genuinely fire-and-forget — the handler never calls `.result()`/awaits it, proven via concurrent-request testing that other requests stay fast while a fetch is in flight) using `tools/wealthsimple_export.py`'s `get_cached_api_or_none()` / `run_export_with_cached_session()`. **Only ever uses the existing cached `tools/session.json`** — no password/2FA path exists in this code at all; missing/expired session degrades to serving last-known-good cached data with `live_sync: {last_attempt_ok: false}` in the response, never a crash or hang. Auto-refresh reuses whichever `--start-date` the most recent manual `ws_import_<start>_<end>.json` used (rule 14 — never a shifting window) and does nothing if no manual export has ever been run yet. `_atomic_write_json` (in `wealthsimple_export.py`) now qualifies its temp filename with the process PID so the server's auto-fetch and a manual CLI run can never collide on the same temp file.
- Current Capital stat card (2026-07-15): a real Wealthsimple NAV (`financials.currentCombined.netLiquidationValue`), not derived from trade P&L — this field is already returned by the same `get_accounts()` call `_build_account_labels()`/`_get_account_ids()` already make (no new API scope, no extra network call). New `_build_account_balances(api, account_labels)` writes `tools/account_balances.json` (gitignored — real balance data) as a sibling to `ws_import_latest.json`, keyed by the same resolved label used for `trade.acc`, **summed** (not overwritten) when two raw accounts resolve to the same label — confirmed against real data that this actually happens (two of Meet's cash sub-accounts both carry the nickname "Meet"); naively overwriting silently dropped one account's real dollar balance. Frontend's "Combined" sums only the accounts the switcher itself tracks (labels actually present in `TRADES`), not every Wealthsimple account on the profile — Meet's FHSA/RRSP/unrelated cash accounts don't inflate it.
- News: tradingview-scraper primary, yfinance fallback, 60s cache
- Chart: dynamic color (green/red), period % + $ gain label, YTD/1D/1W/1M/3M/1Y/5Y timeframes, 30s price poll

### ❌ BROKEN / PENDING
**⚠️ All FIX items below predate the 2026-07-22 engine swap and have NOT been re-checked
against the current engine.** Treat them as unverified reports, not confirmed open bugs —
FIX 2 in particular describes the `/api/financials` path that commit `64a5757` rerouted and
that the 2026-08-01 adapter change altered again.
- FIX 2: Financials — Income Statement YoY Growth shows dashes, Net Income $0.0B (secfsdstools integration in progress)
- FIX 3: loadAnalysis() — ticker search doesn't update the page (fetches but doesn't re-render)
- FIX 4: Chart doesn't update when ticker changes
- FIX 5: Balance Sheet + Cash Flow show raw unformatted numbers
- FIX 6: Stats pills may show mock values instead of live API values

### 🔄 IN PROGRESS
- **Dead code flagged, not removed:** `frontend/index.html`'s bundled `#page-journal` div and
  `renderJournal()` (+ its ~71 supporting functions, `.sin-journal` CSS block) are now
  unreachable — `nav('journal')` redirects to the real `/journal` page (`frontend/journal.html`)
  before ever touching `PAGES.journal`/`#page-journal`. Left in place deliberately (not deleted
  this session) so it doesn't quietly rot as confusing dead code without a record — cleanup
  candidate for a future session, not urgent.
- **⚠️ PRE-SWAP — needs re-confirmation before being treated as current.**
  **Count-gate double-merge redundancy** (found 2026-07-11 during META testing). Every file
  named below (`secfs_revenue.py`, `secfs_net_margin.py`, `code33_engine.py`) was DELETED in
  the 2026-07-22 engine swap, so this describes a pipeline that no longer exists. The same
  class of redundancy may or may not be present in code33-screener — the 2026-07-31 pass did
  observe the revenue series being built twice per call (logged in `bug_report.md`), which
  looks related but was not traced back to this mechanism. Kept for the diagnosis, not as a
  live to-do:
  `secfs_revenue.py`/`secfs_net_margin.py`'s inner secfsdstools→edgartools fallback gates on
  `len(merged) >= n_quarters` (a pure count, no recency check), so it wrongly skips edgartools
  whenever secfsdstools already has ≥16 *old* quarters but is missing the single newest one —
  the normal steady state, since the local secfsdstools bulk dataset lags live filings by ~1
  quarter by design. `code33_engine.py`'s own separate date-aware target-quarter check catches
  the gap and re-fetches via edgartools itself, so this is currently a **performance cost only,
  not a correctness bug** (confirmed: NVDA's 2026-04-26 quarter still reaches output, just after
  a redundant ~19-33s/metric live re-fetch). Hits 13 of 16 regression tickers. Plan (not
  implemented): give the inner check the same recency-awareness instead of a bare count, then
  delete code33_engine.py's now-redundant outer retry block. See `bug_report.md` for full
  writeup — "Solution prepared, not yet implemented".
- ~~**TRT margin output not re-verified under the new NI-tag order (2026-07-09).**~~
  **RESOLVED — this entry was stale.** `bug_report.md` closed it on 2026-07-12: TRT's NI tag
  selection was never wrong (the extracted value exact-matched its filed net income); the real
  defect was the unrelated `_to_m()` unit-conversion bug, fixed in `8f620c4`. CLAUDE.md was
  never updated to match. Kept as a struck-through line rather than deleted so the
  contradiction between the two files is visible rather than silently erased.

---

## ENGINE STATUS
- **CACHE_VERSION:** v31-code33-screener
- **Location:** external `code33-screener` project (`pip install -e`), adapted through
  `utils/code33_adapter.py` — the ONLY in-repo engine file. The old
  `utils/code33_engine.py` + 5 helper modules (`secfs_revenue`, `secfs_net_margin`,
  `edgar_revenue`, `edgar_net_margin`, `sec_edgar`) were deleted 2026-07-22
  (code33-swap branch).
- **Pipeline:** secfsdstools primary (VALIDATED dataset shared with code33-screener via
  project-root `.secfsdstools.cfg` — absolute paths, gitignored, example committed;
  deliberately NOT the ~/.secfsdstools.cfg dataset, which was built with the unsafe
  parallel-download settings), live-EDGAR gap fill for quarters the bulk mirror lacks.
  Validated against SEC filings, a 19-ticker regression baseline, and a 568-ticker
  universe run in the code33-screener project.
- **Concurrency:** pipeline is STRICTLY SEQUENTIAL — a global lock inside
  `utils/code33_adapter.py` serializes every pipeline call server-wide (all endpoints +
  the background scan job). Endpoints offload via `run_in_threadpool` so the event loop
  stays live. Never add a worker pool around the pipeline.
- **Scan:** `/api/scan` is now a background, checkpointed, resumable job
  (`data/scan_jobs/scan_<hash>.csv`, job identity = hash of sorted ticker list; frontend
  polls `GET /api/scan/status` every 3s). Real scans run hours at 15-40s/ticker.
- **Banks:** bank/depository tickers return `status='excluded_bank'` (pipeline refuses to
  score them — their revenue is silently wrong under standard XBRL tags, confirmed on
  FULT). Frontend shows an explicit "EXCLUDED — BANK, NOT YET SUPPORTED" badge and an
  "Excluded — Banks" scan pill, never a silent disappearance.
- **Status semantics:** `_c33_status` (green/yellow/red/insufficient 3-state badge)
  ported VERBATIM into the adapter — unchanged frontend contract.
- **EPS:** still out of scope entirely. Raw `'ni'` is NO LONGER empty as of
  2026-08-01 — it carries real per-quarter net income, alongside new
  `rev_sources`/`ni_sources` and `ni_restated`/`ni_restated_value`. All EPS
  fields remain empty. See the 2026-08-01 entry under LAST UPDATED.
- **Failure labelling:** every `status='insufficient'` path now sets a real
  `excluded_reason`. The success path used to hardcode `''` (11 of 540 tickets on the
  last full scan reported as `insufficient (unspecified)`); `_diagnose_insufficient()`
  in the adapter now names the cause and `_classify_failure()` in `api/server.py`
  buckets it using code33-screener's `universe_scan.py` taxonomy, plus one new bucket
  — **`no reported revenue (pre-revenue company)`**. Diagnosis is derived from the same
  data `_c33_status` sees, and `_yoy_miss_cause()` mirrors `yoy_for()`'s walk exactly so
  the two can never disagree.

---

## GIT WORKFLOW
git add <files>

git commit -m "type: description"

git push
Commit before any new change. Commit message must describe what was validated.

---

## LAST UPDATED
2026-08-01 — **Adapter now exposes what it was discarding; watchlist file deleted;
sector gate added and removed the same day.** (Session ran 2026-07-31 into 2026-08-01;
the data-accuracy investigations behind these changes are dated 2026-07-31 in
`bug_report.md`.) **Nothing in this entry is committed or pushed yet** — `main` is still
2 commits ahead of `origin/main` and `git push` is blocked: `gh auth status` reports the
active account as `monikaarya-work`, which lacks write access to Zoron09/quant-terminal.

  - **Adapter discard fix (`utils/code33_adapter.py`).** `margin_for()` read only
    `net_margin_pct` off each `MarginPoint` and dropped the rest. It is now
    `margin_point_for()`, returning the whole point, and three things it was throwing
    away reach the API:
      1. **Real net income** — `'ni'`/`'ni_end_dates'` are populated instead of hardcoded
         `[]`. (Supersedes the ENGINE STATUS note that called raw `'ni'` intentionally
         empty.) Verified nothing consumed the empty contract first: `api/server.py`
         reads only `npm_ends`, and the one `ni:` hit in `frontend/index.html` is
         hardcoded demo data, not an API read.
      2. **Per-quarter provenance** — new `'rev_sources'`/`'ni_sources'`, the un-flattened
         form of the `'sources'` summary (which is still emitted unchanged). Upstream
         vocabulary verbatim: `reported` = secfsdstools, `edgartools` = live gap fill,
         `derived_fy_minus_quarters` = Q4 back-solved from the 10-K.
      3. **Restatement flags** — new `'ni_restated'`/`'ni_restated_value'`. The pipeline
         already detected restatements and the adapter discarded the finding. AES proves
         the cost: its 2024-06-30 quarter is served as $185.0M when AES itself later
         restated it to $276.0M — a 3.1pp margin error feeding the margin-expansion leg.
         The engine still reports the as-first-filed value; this only surfaces that a
         revision exists. Which value *should* win is an open policy question.
    `ni_plausible`/`revenue_plausible` deliberately left unexposed. Purely additive — no
    field removed or renamed, no revenue or margin value changed. Regression: AES, UNP,
    MU, INTC, JBLU, IQV byte-identical on rev/npm/status/sources against a baseline
    captured from the live API before the edit.

  - **`data/sp500_tickers.json` deleted.** Four stale tickers were fixed first (ABC→COR,
    SQ→XYZ, WBA and K removed — all four confirmed against SEC's live ticker map as
    resolving to nothing; BRK.B left alone, it is a dot-vs-hyphen false positive that
    `normalize_ticker()` already handles). Then the file was removed outright: grep of
    the whole repo including both frontend bundles found **zero code consumers** — its
    only reader, `tools/watchlist_ticker_audit.py`, was deleted in the 2026-07-22 swap.
    Deletion is staged. Note the force-delete discarded the ticker fix before it was
    committed, so that edit leaves no trace in git history.
    **Stale prose:** the 2026-07-09 entry below still describes this file, plus
    `tools/watchlist_ticker_audit.py` and `tools/preflight_checks.py` — all three now
    gone. Left as-is deliberately: it is a dated historical record, accurate when
    written. Only its "watchlist cleanup not yet done — pending go-ahead" status line is
    superseded, by this entry.

  - **Sector exclusion: gate added, then removed same day — final state is
    informational-only.** The reported symptom was EIX (Utilities) scoring GREEN on the
    last full scan. Root cause was not the documented "gating gap": the swap deleted the
    sector logic entirely, leaving `sector_excluded` a hardcoded `False` literal with
    nothing computing it (code33-screener has no sector concept — its bank check is
    explicitly "deliberately NOT sector labels"). The `EXCL_SECTORS`/
    `EXCL_INDUSTRY_KEYWORDS`/`REIT_KEYWORDS` lists were recovered verbatim from
    `dc77f59^` and a hard gate wired in, returning `status='excluded_sector'` before the
    pipeline ran.
    **Reversed the same day on review of Minervini's actual methodology:** these are
    defensive/late-cycle sectors that Code 33's own growth and margin criteria are meant
    to filter out on the numbers. A pre-scoring gate pre-empts that judgement and hides
    the evidence for it. The gate is gone; `_sector_flags()` and both lists stay, and
    `sector_excluded`/`excluded_sector_name`/`is_reit` are returned as metadata on every
    path including the no-data exits. EIX and AES now score normally and still report
    `sector: Utilities`.
    **The bank exclusion was deliberately NOT touched** — banks are refused for a proven
    data-correctness fault (revenue silently wrong under standard tags, confirmed on
    FULT), which is a different category from a sector-fit judgement.
    **Cost, flagged not fixed:** `_sector_flags()` makes a yfinance `.info` call per
    ticker inside the globally-serialized pipeline. With the gate it paid for itself by
    skipping the pull; now every ticker pays it for metadata only.
    **Worth revisiting:** the keyword list matches substrings against a yfinance
    free-text field — `'chemical'` catches both "Specialty Chemicals" and "Agricultural
    Chemicals", and a vendor relabelling silently changes behaviour.
    **Removed entirely hours later, same session.** With no gating behaviour left, the flags
    were one extra yfinance `.info` call per ticker — multiplied across a 500+ ticker scan —
    for a label nothing consumed. `_sector_flags()`, both keyword lists, `REIT_KEYWORDS` and
    the yfinance import are gone; `sector_excluded`/`excluded_sector_name`/`is_reit` are back
    to their original hardcoded `False`/`''`/`False` on every return path. Net effect of the
    day's sector work on the adapter: zero, minus a comment explaining why there is no gate.

  - **Verification lesson — confirm ONE listener on port 8000 before trusting any
    result.** A post-fix pull showed the sector gate doing nothing; it was working. Three
    processes were listening on 8000 simultaneously (two stale servers plus orphaned
    `multiprocessing` children holding inherited socket handles), and requests were
    landing on pre-fix code. `Stop-Process` on the reloader PID is not sufficient — check
    `netstat -ano | Select-String ":8000.*LISTENING"` returns exactly one row, and kill
    orphaned `python.exe` children whose command line contains `multiprocessing`. This is
    the same trap recorded in `bug_report.md` under commit `64a5757`.

  - **`bug_report.md` — new 2026-07-31 sections** from two 10-ticker data-accuracy passes
    (20 tickers, all verified against `data.sec.gov` directly). Confirmed defects: the
    restatement discard above; **ICE missing an already-filed quarter** (2026-06-30,
    filed 2026-07-30, invisible because `expected_quarter_ends()` won't target it until
    ~45 days past period end — a real blind window, unlike the MU case previously waved
    off); **the ±1000% margin plausibility guard lost in the swap** (commit `990bcba`'s
    TRT tripwire was never ported — CRSP's -24450% proves values now flow through);
    **blank fiscal labels on every edgartools-filled quarter** (`pipeline.py:95-96` sets
    `fy=None, fp=None`; FDS shows two); **SLXN never reaching the pre-revenue bucket**
    (the `<5 quarters` guard returns before `_diagnose_insufficient()` runs). Cleared
    after investigation: ORA, LMND, ESRT, ICE, NUE, COR — all matched SEC exactly;
    the LMND/ICE/ESRT/AES gaps against TradingView are vendor definitional differences,
    now documented per ticker.

2026-07-31 — **Unlabelled-failure reporting gap closed (branch
`insufficient-reason-labels`, NOT merged — held for review)**. `_c33_status` can return
'insufficient' from the adapter's SUCCESS path (both series pulled fine, but a leg had
fewer than the 3 clean values the 3-quarter window needs); that path hardcoded
`excluded_reason=''`, so 11 of 540 tickers on the last full scan collapsed into one
anonymous `insufficient (unspecified)` bucket that told the operator nothing and gave
the circuit breaker no cause to group on.
  - Traced all 11 to real root causes before writing any fix (live pipeline + live
    EDGAR, not inference). Two genuine clusters: **5 pre-revenue companies** (RVMD,
    XENE, SYRE, DNLI, PLSE — 9-11 of 12 quarters report $0 or no revenue line;
    confirmed against live EDGAR that RVMD/DNLI/SYRE file a revenue concept valued
    exactly 0.00 for 2025+, so this is a company property, not a data gap) and
    **6 short-history companies** (SDRL, VG, INDV, ALMS, BIOA, SEPN — 5-6 quarters,
    fewer than the 7 needed to form 3 YoY pairs).
  - New bucket: `no reported revenue (pre-revenue company)`. Zero revenue breaks BOTH
    legs simultaneously — net margin is undefined against a zero denominator
    (`net_margin.py` guards `revenue != 0`) and YoY is undefined against a zero base —
    so none of the existing categories described it. The other 6 map onto the existing
    `insufficient revenue history`.
  - **Finding worth acting on separately:** within the short-history six, SDRL and INDV
    are NOT young companies. Both are former foreign private issuers that converted to
    domestic filing in 2025 (SDRL: 6× 20-F 2019-2024, first 10-Q 2025-02-27; INDV: 20-F
    2024-03-06, first 10-Q 2025-03-03). Their pre-conversion history is annual-only
    20-F, which this pipeline correctly excludes. Mechanically identical outcome, very
    different meaning. Not separately bucketed — distinguishing it needs a per-ticker
    filing-history lookup, a real cost across a 540-ticker scan. Flagged, not actioned.
  - Verified: all 11 now carry a specific reason and a named bucket, zero left
    unspecified; 14 spot-check tickers (3 green, 2 yellow, 5 red incl. AAPL/CHEF/TGT
    from the regression baseline, 2 excluded_bank) byte-identical to the pre-fix scan on
    status, rev_yoy and margin. Metadata only — the diff's sole deletion is the
    hardcoded `''`; frontend has zero references to `excluded_reason`.

2026-07-22 — **Code 33 engine swap (branch `code33-swap`, NOT merged to main)**: old
in-repo engine fully removed (`utils/code33_engine.py` + secfs_revenue/secfs_net_margin/
edgar_revenue/edgar_net_margin/sec_edgar, plus their orphaned consumers
tools/preflight_checks.py, tools/watchlist_ticker_audit.py, tools/engine_accuracy_check.py,
tools/run_c33_batch.py, tests/test_preflight_checks.py) and replaced by the externally
validated code33-screener pipeline via `utils/code33_adapter.py` (global pipeline lock,
verbatim `_c33_status` port, ascending-array contract preserved). `/api/scan` rebuilt as a
background checkpointed resumable job with `GET /api/scan/status` polling; frontend
patched (tools/patch_frontend_scan.py — runScan polling loop, scan progress line,
excluded-banks pill, EXCLUDED — BANK badge) within the bundled-SPA patch rules; world
grid/nav untouched. Wealthsimple/journal/analytics/portfolio paths confirmed untouched
by grep before AND after deletion. Partial validation passed (bank exclusion end-to-end +
regression-baseline spot checks); full 300-500-ticker scan deliberately NOT yet run —
awaiting final ticker list. See ENGINE STATUS above for the new architecture.

2026-07-13 — **4-commit sequence complete**: TRT's `-230,303%` margin corruption led to a
full chain — `8f620c4` fixed the root-cause `_to_m()` unit-conversion bug (4 duplicate
copies across secfs_*/edgar_* modules), `64a5757` routed `/api/financials/{ticker}` through
`code33_engine.py`'s own date-aware gap detection instead of calling secfsdstools/edgartools
directly, `9753f34` added a yfinance third-leg revenue fallback (fill-only, revenue-only,
provenance-tagged) for gaps neither SEC-sourced tool can fill, and `990bcba` adds a
`±1000%` plausibility guard on margin values as a last line of defense against the same bug
class recurring silently. Full detail, including honest verification notes (BLK/MU/CMP
weren't actually exercised by the yfinance leg on verification day, for three separate
reasons; CPTP unexpectedly was), in `bug_report.md`.

2026-07-11 — Corrected a stale IN PROGRESS note. The "newest quarter invisible" bug in
`edgar_revenue.py`/`edgar_net_margin.py` (originally confirmed 2026-07-07) was actually fixed
two days later in commit `9c421c5` (2026-07-09) — CLAUDE.md was never updated to reflect that,
so it sat listed as "pending explicit go-ahead, not yet implemented" for two days after
shipping. Re-verified live again today during NVDA reproduction testing: newest quarter
2026-04-26 confirmed present in `get_code33_data("NVDA")`'s output. RESOLVED, not open — see
`bug_report.md` for the full writeup. (Separately, a *different*, still-open bug in
`secfs_revenue.py`/`secfs_net_margin.py` was found today and now occupies the IN PROGRESS slot
below — confirmed via commit diff and live testing to be an unrelated mechanism, not a
resurfacing of the 07-07 bug.)

2026-07-10 — Full cleanup pass (stale artifacts + dead caching decorator), user-confirmed
before deletion. Pre-checks first: grepped all live code for imports reaching into archive/
(none found), grepped for "streamlit" case-insensitive (found it wasn't just code33_engine.py
— utils/sec_edgar.py also imports it, with 4 more `@st.cache_data` decorators; requirements.txt
still declares streamlit>=1.28.0, correctly left alone), checked tests/ for cache-behavior
tests (none exist, so removal couldn't break a real assertion).
  - Deleted (git rm, tracked files): `quick_scan.py`, `run_batch.py` (root scratch scripts),
    `Minervini builder Managed copy_2026-06-23.csv`, `Minervini_builder_Managed_2026-04-28.csv`
    (superseded ticker-list inputs), `Code33_Results_2026-06-23.csv`,
    `Code33_Results_2026-05-25.csv` (stale scan outputs sitting in repo root, risked being
    mistaken for current data), `archive/tools/*.py` (6 old audit scripts, superseded by
    `tools/engine_accuracy_check.py`/`preflight_checks.py`/`watchlist_ticker_audit.py`),
    `archive/utils/screener_db.py` (unused SQLite cache module, no db file existed on disk).
    `archive/` is now gone entirely (both subdirs were emptied).
  - Deleted all `__pycache__/`/`*.pyc` repo-wide (already gitignored, untracked) — included two
    orphaned bytecode files whose source `.py` no longer exists (`edgar_net_income.pyc`,
    `test_code33_regression.pyc` x2), leftover from earlier code removals.
  - Removed dead `import streamlit as st` + `@st.cache_data` from `code33_engine.py`
    (`get_code33_data`'s 24h result cache) — the app is FastAPI-only now, no Streamlit runtime
    ever exists, so this was silently caching in-memory per server process with no way to bust
    it short of a restart. Real risk confirmed: `CACHE_VERSION` (still 'v30') was NOT bumped
    across the last 4 NI/revenue logic fix commits (5f680ae, 9c421c5, 186d24d, 8d455cf) — none
    of them touch `code33_engine.py` — so a long-running server could've served pre-fix cached
    numbers for up to 24h post-deploy. Pure removal here, no replacement, per plan.
  - Expanded scope (user-approved) to `utils/sec_edgar.py`'s matching 4 decorators. Removing
    `_get_ticker_mapping()`'s decorator outright caused a **real regression**, caught by
    verification, not shipped: that function is zero-arg and fetches SEC's full multi-MB
    ticker→CIK map; `get_cik()` (called on every single ticker by
    `secfs_net_margin.py`/`secfs_revenue.py`/`preflight_checks.py`/`watchlist_ticker_audit.py`)
    calls it every time. With the decorator, one process-lifetime fetch was reused for every
    ticker in a batch; without it, a 16-ticker verification run refetched that file 16x back to
    back, and mid-run degraded into rate-limit/timeout failures that cascaded into 11 of 16
    tickers (LIN, JNJ, CB, AME, BLK, NVDA, AMD, MSFT, AIP, CELH, +partial CMP) coming back fully
    `insufficient`. Fixed by replacing that one decorator with `functools.lru_cache(maxsize=1)`
    (explicit stdlib, no streamlit dependency, same one-fetch-per-process effect — this
    function has no meaningful staleness risk, SEC's ticker map doesn't change within a
    process's lifetime, so a replacement was correct here unlike code33_engine.py's case). The
    other 3 decorators (`get_recent_filings`, `get_insider_filings`, `get_key_filings`) had zero
    callers anywhere in the live codebase — removed clean, no behavior change possible.
  - Re-verified after the lru_cache fix: all 10 previously-collapsed tickers back to matching
    baseline exactly (LIN, BLK, NVDA, AMD, MSFT, AIP, CELH byte-identical). Residual diffs on
    GOOGL/MU/CMP/PED/CPTP/TEAM/JNJ/CB/AME are the pre-existing newest-quarter edgartools bug
    above, not new — confirmed same shape (one quarter at the edge, filled/missing toggling)
    across two runs 45min apart, unrelated to any file this cleanup touched.
  - Server boot-tested: `run.py` starts clean, no import errors; `GET /api/ticker/MU` over real
    HTTP returned 200 with full data; server stopped cleanly after.
  - `tests/test_preflight_checks.py`: 6 passed, 1 xfailed (TRT, pre-existing) — unchanged from
    documented baseline.
  - `requirements.txt` untouched (out of scope for this cleanup) — worth noting though: after
    both files' edits, `streamlit` is no longer imported anywhere in the live codebase at all
    (checked: zero hits repo-wide outside `.venv`), so the `streamlit>=1.28.0` line is now a
    genuinely unused dependency, not just an unused import. Flagging, not removing — a
    dependency-list change is a separate decision from this cleanup.

2026-07-09 — Fixed net-margin numerator: engine was using plain "Net Income" (NetIncomeLoss)
instead of "Net Income Attributable to Common Stockholders" (post-preferred-dividend) for
companies with preferred stock. Confirmed via CELH's real Q3 2024 10-Q filing (SEC EDGAR,
not through edgartools/secfsdstools abstraction): NetIncomeLoss = $6,356,000 vs actual
attributable-to-common = $(557,000) after $6,913,000 in Series A preferred dividends —
Macrotrends independently reports the common-stockholders figure, and Minervini's own EPS
convention always uses it, so margin and EPS now share the same numerator convention.
  - utils/secfs_revenue.py: reordered `_NI_TAGS` — `NetIncomeLossAvailableToCommonStockholdersBasic`
    moved from last to first priority.
  - utils/edgar_net_margin.py (protected file — this counts as the confirmed-bug sign-off
    under rule 1): swapped Tier 1/Tier 2 in `_ni_row()`, same reorder.
  - Verified safe as a pure reorder: companies with no preferred stock (checked directly
    against the local secfsdstools parquet DB, not assumed) never file this tag at all —
    confirmed absent across 8 quarters each for GOOGL, MU, CMP, PED, CPTP, TEAM, LIN, JNJ,
    CB, AME, BLK, NVDA, AMD, MSFT, AIP — so lookup falls through to NetIncomeLoss unchanged
    for them. Regression-tested: all 15 byte-identical before/after.
  - CELH validated: all 8 quarters' margins shifted as expected; Q3 2024 net income now
    exact-matches the filing ($-557,000), margin flipped +2.41% → -0.23% (negative, correct
    direction vs Macrotrends).
  - TRT investigated as a possible edge case (initially looked like duplicate/ambiguous
    NetIncomeLossAvailableToCommonStockholdersBasic rows for the same period) but cleared —
    the duplication was a bug in a throwaway diagnostic script that omitted an XBRL `ddate`
    filter (conflated the current quarter with the filing's own prior-year comparative
    column); production code (`_own_period_value`) already pins on `ddate` correctly and was
    never affected. Real finding: TRT's tag nets out non-controlling interest, not preferred
    dividends (TRT has no preferred stock) — same tag, different economic adjustment. TRT
    was deliberately excluded from this fix's regression set and has not been explicitly
    re-verified under the new tag order (see IN PROGRESS above).

2026-07-09 — Added 4 new preflight detectors to tools/preflight_checks.py, closing gaps
found across 3 rounds of independent quarter-identification verification against raw SEC
EDGAR data (data.sec.gov, direct HTTP, no secfsdstools/edgartools). _target_quarter_ends's
date math itself was confirmed correct throughout (52-ticker systematic sample from
data/sp500_tickers.json: 96% clean match, zero date-math bugs) — all 4 fixes are
identity-resolution problems upstream of it:
  - check_foreign_annual_only: 20-F/40-F annual-only filers (BIDU, BABA) — no 10-Q ever
    exists, Code33's quarterly methodology structurally doesn't apply.
  - check_cik_discontinuity: tracked-universe tickers whose *current* CIK has <3 years of
    real SEC history — catches BlackRock/BLK-type holdco reorgs (confirmed: BLK's current
    CIK 2012383 only goes back to Feb 2024; the real 2006-2024 history sits under CIK
    1364742, renamed by SEC itself to "BlackRock Finance, Inc." 2024-09-26). Flags for
    manual review only — does not attempt to recover pre-reorg history.
  - check_ticker_resolution: ticker doesn't resolve via SEC's current company_tickers.json
    at all (renamed or taken private) — reported as a distinct watchlist-maintenance
    category, not a generic data failure.
  - check_deregistered: Form 15 in history AND no *operating* filings (10-Q/10-K/8-K/
    20-F/40-F — excludes third-party SC 13G/13D ownership disclosures, which keep
    appearing under a dead CIK indefinitely) for 200+ days afterward. A bare Form 15 alone
    is NOT sufficient signal — 5 tickers (AME, CB, JNJ, LIN, TEAM) have one in their
    history but still file normally; only CPTP (Form 15 filed 2025-02-11, zero operating
    filings since) genuinely qualifies.

New standalone tool: tools/watchlist_ticker_audit.py — cross-checks data/sp500_tickers.json
against SEC's current ticker map. Run once: found 5 stale tickers in the 208-ticker
watchlist — ABC (renamed COR/Cencora), WBA (taken private), K (Kellanova, acquired by
Mars), SQ (renamed XYZ/Block), and BRK.B (a false positive — SEC lists it as "BRK-B" with
a hyphen; utils/sec_edgar.py's get_cik() ticker normalization doesn't handle the dot/hyphen
convention difference, not a real corporate event). Watchlist cleanup (removing/renaming
the 4 genuine stale tickers) not yet done — flagged, not actioned, pending go-ahead.
All 7 preflight detectors verified with real tickers; existing test_preflight_checks.py
suite still passes unchanged (6 passed, 1 xfailed — TRT, pre-existing).

Prior (2026-07-07): Removed Finnhub/FMP/raw-XBRL-tier/yfinance-fallback from
code33_engine.py; redesigned revenue+margin fetch to quarters-first targeted gap-fill;
fixed real-filed-date and fiscal quarter-label mismatches (CMP, NVDA); deleted 5
confirmed-dead files from the Finnhub/FMP era. Confirmed but not yet fixed:
edgar_revenue.py/edgar_net_margin.py structural bug hiding each ticker's newest quarter
until its fiscal year closes — [fixed 2026-07-09, commit 9c421c5; see 2026-07-11 entry above].
