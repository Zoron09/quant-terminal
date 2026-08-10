# Bug Report — Quant Terminal Engine

Authoritative bug-status reference for the current engine version. Scope: bugs found
during the manual ticker-testing initiative, 2026-07-09 to 2026-07-12, tied to the
current engine only. Older/historical bugs (ESOA, EDRY, PED, KEWL, WSR, sector-exclusion
gaps, etc.) are out of scope here — tracked elsewhere. The financial-sector/bank
net-margin bug (JPM-type) is known, deliberately deferred, and also out of scope.

---

## Resolved

### CELH net income bug — wrong NI tag for preferred-stock companies
- **Commit:** `5f680ae` (2026-07-09)
- **What it was:** Net margin (and EPS convention) used plain `NetIncomeLoss` instead of
  `NetIncomeLossAvailableToCommonStockholdersBasic` for companies with preferred stock —
  wrong numerator whenever preferred dividends materially change the common-stockholders
  figure.
- **Root cause:** `_NI_TAGS` priority order in `secfs_revenue.py` and the Tier 1/Tier 2
  order in `edgar_net_margin.py::_ni_row()` put `NetIncomeLossAvailableToCommonStockholdersBasic`
  *last* instead of *first*, so plain `NetIncomeLoss` matched first and the preferred-dividend
  deduction was silently skipped.
- **How found:** Direct SEC EDGAR check (not through the secfsdstools/edgartools abstraction)
  on CELH's real Q3 2024 10-Q: `NetIncomeLoss` = $6,356,000 (positive) vs actual
  attributable-to-common = $(557,000) (negative) after $6,913,000 in Series A preferred
  dividends. Macrotrends independently reports the common-stockholders figure — confirmed
  the engine's number didn't match a real external source.
- **How fixed:** Reordered `_NI_TAGS` in `secfs_revenue.py`; swapped Tier 1/Tier 2 in
  `edgar_net_margin.py::_ni_row()`. Pure tag-priority reorder, no other logic touched.
- **Verification:** Checked all other tracked tickers (GOOGL, MU, CMP, PED, CPTP, TEAM, LIN,
  JNJ, CB, AME, BLK, NVDA, AMD, MSFT, AIP) directly against the local secfsdstools parquet DB
  — confirmed none of them ever file the `...CommonStockholdersBasic` tag at all, so the
  reorder is a no-op for them (byte-identical output before/after, 15/15). CELH itself:
  net income now exact-matches the filing ($-557,000); margin flipped +2.41% → -0.23%, correct
  sign vs Macrotrends.

### _to_m() unit-conversion bug — sub-$1M values corrupted or silently zeroed
- **Commit:** `8f620c4` (2026-07-12)
- **What it was:** Two separate defects in the same helper function, existing as four
  independent copies across `edgar_revenue.py`, `edgar_net_margin.py`, `secfs_revenue.py`,
  `secfs_net_margin.py`:
  1. `edgar_revenue.py`/`edgar_net_margin.py`'s `_to_m()` skipped the division for any raw
     value under $1,000,000 (`return val if abs(val) < 1_000_000 else val/1_000_000`),
     assuming "small raw value means it's already in millions." Wrong: XBRL values are
     always raw USD regardless of company size. A real -$38,000 net income was left as
     `-38000.0` and then treated downstream as *-38000.0 million dollars* — a
     unit-magnitude error of exactly 10^6.
  2. `secfs_revenue.py`/`secfs_net_margin.py`'s `_to_m()` already divided unconditionally
     (this exact skip bug was fixed here once before — see the ASYS case below) but rounded
     to 1 decimal place, which has the same erasure effect for sub-$1M values: -$38,000 in
     millions is -0.038, and `round(-0.038, 1)` is `-0.0` — silently losing sign and
     magnitude, displaying as a healthy 0% margin instead of a real small loss.
- **Root cause / how found:** Confirmed live on TRT: `get_code33_data('TRT')` produced
  `npm = -230303.03` for its newest quarter (2026-03-31) — implying a ~$38 billion net loss
  on $16.5M revenue. Pulled TRT's actual 10-Q directly from SEC EDGAR (accession
  `0001437749-26-016914`, filed 2026-05-14): real reported net income is **-$38,000**.
  `-38000 / 1_000_000 × 100 / 16.5 = -230303.03` — exact match, confirming defect #1 above
  as the live mechanism. Checked the sibling `secfs_*` modules for the same class of problem
  even though they don't have the skip bug — found defect #2 (1-decimal rounding) live with
  the identical TRT numbers, confirming both needed the same fix.
  This is the same bug class documented once before and only half-fixed: `secfs_revenue.py`'s
  own `_to_m()` docstring already recorded the ASYS case (real NI $312,000 left unconverted,
  producing a >500,000% margin) and was fixed in the `secfs_*` pair — but that fix never got
  ported to the `edgar_*` pair, which is why the same bug class recurred, now confirmed on TRT.
- **How fixed:** All four `_to_m()` implementations now divide unconditionally and round to
  4 decimal places (not 1) — sub-$1M values keep correct sign and magnitude down to roughly
  $100 raw. Downstream margin-percentage rounding (2dp) was checked and is fine now that its
  input is correct.
- **Verification:** TRT's newest quarter now shows `npm = -0.23` — exact match to the real
  filed number (-$38,000 / $16.5M × 100 = -0.230303...%), correct sign and magnitude, not
  -230,303% and not 0.0%. Spot-checked AIP, CELH, TEAM, PED, CMP (other small-caps flagged as
  exposed to this bug class) — no absurd (>1000%) or suspiciously-exact-zero margins on any
  quarter. Regression: NVDA, MSFT, GOOGL byte-identical to their pre-fix baseline (their NI is
  always well over $1M, so they never hit the broken branch either way).
- **Call-site audit:** confirmed every call site of `_to_m()` in both `edgar_revenue.py` and
  `edgar_net_margin.py` feeds only dollar-denominated Revenue/Net-Income rows — nothing
  per-share or already-ratio-valued flows through it, so the unconditional-divide fix is safe
  everywhere it's used.
- **Follow-up / tech debt (not done in this commit):** four independent copies of `_to_m()`
  exist across these two module pairs. This exact bug class recurred specifically *because* a
  fix landed in one pair (`secfs_*`, for the ASYS case) and never propagated to the other
  (`edgar_*`). Recommend consolidating into a single shared utility function so a future fix
  can't diverge again the same way.

### /api/financials/{ticker} endpoint — newest-quarter margin null, wrong dates
- **Commit:** `64a5757` (2026-07-12)
- **What it was:** `/api/financials/{ticker}` called `secfs_revenue.py`/`secfs_net_margin.py`
  directly instead of going through `code33_engine.py`'s date-aware gap detection. Confirmed
  live on 16 of 20 tracked tickers: newest-quarter `net_margin` was `null` (no fallback for
  margin at all), and revenue — where present — came only from a yfinance fallback that uses
  yfinance's own calendar-normalized quarter-end date, not the real SEC-filed date (e.g. NVDA
  showed `2026-04-30` instead of the real `2026-04-26`; FN showed `2026-03-31` instead of the
  real `2026-03-27`).
- **Root cause:** this endpoint was a second, independent caller of
  `secfs_revenue.py`/`secfs_net_margin.py` with no compensating layer — unlike
  `code33_engine.py`'s callers, which are protected by its own `_target_quarter_ends`/
  `_fill_target_quarters` date-aware gap-fill. See the "Count-gate double-merge redundancy"
  entry above for the underlying mechanism this endpoint had no protection against.
- **How fixed:** routed the endpoint through `get_code33_data(t, n_quarters=12)` instead —
  added an optional `n_quarters` parameter to `get_code33_data()`/`_get_code33_data_inner()`
  (default 8, so every existing caller is unaffected) so this endpoint can request its own
  12-quarter buffer (8 display quarters + 4 for its own index-based YoY calc) through the
  same date-aware path everything else already trusts. Added a `_closest_date()` proximity
  matcher (10-day tolerance) so `get_code33_data`'s real filed dates correctly merge with
  yfinance's own EPS-only date series instead of splitting the same quarter into two
  incomplete rows. Dropped the old yfinance-revenue-fallback block — no longer needed.
- **Verification method — note for future sessions:** verified via a **fresh Python
  interpreter per ticker calling `api.server.financials()` directly**, not real HTTP against
  a running `uvicorn --reload` server. Real-HTTP verification produced false "still broken"
  results earlier in this same work session: the `--reload` worker process did not reliably
  restart on file changes, so requests kept hitting pre-fix code (TRT briefly appeared to
  still show its Commit-1-fixed garbage margin, purely because the live worker was stale) —
  wasted significant time chasing a phantom regression that didn't exist in the actual code.
  If verifying this endpoint again via real HTTP, explicitly confirm the worker PID is fresh
  (check `Started server process [PID]` in the boot log against `Get-Process`) before trusting
  any response — don't assume `--reload` picked up an edit.
- **Verified (fresh-interpreter method):** NVDA (margin 71.46, date corrected to 2026-04-26),
  META (margin 47.54), FN (margin 10.31, date corrected to 2026-03-27), TRT (margin -0.23,
  confirms Commit 1's fix holds through this path), GOOGL (56.94) and CELH (10.87) both fully
  complete, nothing lost. Test suite unchanged (6 passed, 1 xfailed). Server boots clean.
- **Known, bounded gap at the time — closed (mechanism-wise) by Commit 3** (see below): BLK,
  MU, and CMP lost newest-quarter revenue and/or margin under this routing.

### yfinance revenue fallback — third leg for gaps secfsdstools/edgartools can't fill
- **Commit:** `9753f34` (2026-07-12)
- **What it closes:** the BLK/MU/CMP "known, bounded gap" flagged in the entry above.
- **Design:** added a third leg to `get_code33_data()`'s revenue pipeline —
  secfsdstools → edgartools → **yfinance** — living inside `code33_engine.py` itself (not
  `api/server.py`), so every consumer of the engine benefits. Constraints, all verified:
  - **Fill-only:** `_fill_target_quarters()` gained an optional `tertiary_pairs` parameter,
    only consulted for a target quarter when both `primary_pairs` (secfsdstools) and
    `secondary_pairs` (edgartools) have no match — never overrides an existing value.
  - **Revenue-only:** no yfinance NI/margin leg was added. Margin stays `null` when
    unavailable — that's correct, not a bug, per the mixed-accounting-basis concern.
  - **Provenance-tagged:** `sources['rev']` gets a `+yfinance` suffix when it contributes,
    and a new `sources['rev_yfinance_filled']` list names exactly which target quarters
    (by date) yfinance filled — empty for every ticker that doesn't need it.
  - **Unit discipline:** added `_yf_to_m()`, matching Commit 1's fixed `_to_m()` precision
    (divide unconditionally, round to 4 decimals) — yfinance's `quarterly_income_stmt`
    already returns raw USD like the other two sources, so there's no skip-bug to inherit,
    but routing through the same discipline keeps precision uniform across all three legs.
- **Proof the mechanism works — EDRY:** secfsdstools has zero quarters for EDRY, and
  edgartools throws an exception for it (confirmed in an earlier session). Before this
  commit: 8 of 8 target quarters missing. After: yfinance filled 5 of 8 (the 5 most recent —
  yfinance's `quarterly_income_stmt` only returns roughly its 5 newest quarters, confirmed
  by direct inspection). Cross-checked against Macrotrends: yfinance's 4 most recent
  quarters sum to ≈$55.8M, consistent with Macrotrends' reported TTM-as-of-2026-03-31 of
  $0.06B (~$60M) at that page's rounding precision — no scaling error, the kind of bug
  Commit 1 fixed.
- **Honest result on the three originally-named tickers — none were actually exercised on
  verification day, for three different, unrelated reasons (mechanism confirmed correct via
  EDRY above; these three just didn't happen to need it *today*):**
  - **BLK:** its specific gap dates (2024-06-30, 2024-12-31) are older than yfinance's
    ~5-quarter lookback window — confirmed by direct inspection of
    `_yfinance_revenue_pairs('BLK')`, which only returns 2025-03-31 through 2026-03-31. A
    real data-availability limit, not a bug in this fix. BLK's revenue stays `insufficient`
    at `n_quarters=12` (and even at the default 8) — this is unchanged from before this
    commit (verified byte-identical against pre-Commit-3 code) and is itself a pre-existing
    characteristic of BLK's sparse history under its current (post-reorg) CIK, not something
    this or any revenue-fallback commit can fix.
  - **MU:** its true newest quarter (2026-05-31) still isn't inside `get_code33_data`'s
    expected target window (the existing 45-day filing-lag buffer in `_target_quarter_ends`
    hasn't been crossed yet as of this verification) — so the fallback is correctly never
    even attempted for it yet. Not a bug; will self-resolve once the quarter is due, or the
    yfinance leg will pick it up if secfsdstools/edgartools still lag it at that point.
  - **CMP:** the separately-tracked, pre-existing count-gate flakiness (see "Count-gate
    double-merge redundancy" above) meant edgartools itself happened to succeed on this
    verification run, so revenue was already fully covered before yfinance was ever
    consulted (`rev_yfinance_filled: []`).
- **Unexpected (but correct) bonus — CPTP:** regression-checking the other 16 tracked
  tickers turned up one surprise: CPTP unexpectedly showed `+yfinance` with 5 quarters
  filled. Investigated rather than assumed a problem: `edgartools`'s `Company()` resolution
  is entirely independent of `utils/sec_edgar.py::get_cik()` (which secfsdstools relies on,
  and which returns `None` for CPTP — confirmed in an earlier session, CPTP is delisted/
  deregistered per its Form 15). edgartools's own internal ticker database still resolves
  CPTP, so it was already getting edgartools-only revenue before this commit; yfinance now
  correctly fills the specific quarters edgartools itself couldn't reach. Fill-only behavior
  working exactly as designed, on a ticker beyond the three originally named — not a
  regression. CPTP's broader data-quality status remains a separate, already-tracked concern
  (`check_deregistered` in `tools/preflight_checks.py`), unaffected by this note.
- **Regression check:** the other 16 tracked tickers (GOOGL, PED, TEAM, LIN, JNJ, CB, AME,
  NVDA, AMD, MSFT, AIP, CELH, FN, META, TRT, plus CPTP as the one fill-only exception above)
  — 15 of 16 show zero yfinance involvement (`rev_yfinance_filled: []`, no `+yfinance`
  suffix), confirming the new leg is inert for every ticker that doesn't need it, exactly as
  designed (it only even calls yfinance when `_rev_missing_after_edgar` is non-empty).
- **Verification:** test suite unchanged (6 passed, 1 xfailed). Server boots clean, one
  tracked boot/stop cycle confirmed both PIDs actually dead afterward (per the Commit 2
  lesson).
- **Dependency note:** this adds a new `yfinance` call path inside `code33_engine.py`
  itself (previously yfinance was only used for `.info`/sector/FYE lookups and, separately,
  in `api/server.py` for price/EPS/balance-sheet data — never for revenue inside the engine's
  own pipeline). A broader review of yfinance's overall role and reliability across the
  codebase is planned separately — out of scope for this commit.

### Margin plausibility guard — defense-in-depth against a repeat of the TRT bug class
- **Commit:** `990bcba` (2026-07-13)
- **What it is:** a tripwire, not primarily a nuller — the 4th and final commit in the
  sequence that started with the TRT `-230,303%` corruption (Commit 1). Rather than trust
  every margin percentage that reaches `code33_engine.py`, any value outside roughly
  `±1000%` is now rejected before it can reach output, on the reasoning that no
  screener-meaningful margin lands out there — real one-time gains or tax benefits can
  legitimately push margin past ±200%, so the bound is deliberately loose: it's meant to
  catch a future scaling/extraction bug like Commit 1's, not flag unusual-but-real quarters.
- **Where:** added `_is_plausible_margin()` in `code33_engine.py`, called at the two points
  where `net_margin_pct` is pulled in from `secfs_net_margin.py`/`edgar_net_margin.py` into
  `code33_engine.py`'s own merge pipeline. Note on placement: `code33_engine.py` doesn't
  actually compute margin from NI/revenue anywhere itself — that division happens upstream,
  in those two files — so this guards the point where `code33_engine.py` *ingests* an
  already-computed value, which is the earliest point inside `code33_engine.py` where a
  bad value could be intercepted, and (since nothing else currently calls those two
  functions directly) covers every real caller of `get_code33_data()` today.
- **On rejection:** the pair is excluded from that source's list entirely, not replaced with
  a null placeholder — this leaves the quarter open for the *other* source (secfsdstools vs.
  edgartools) to fill instead, and it only ends up `null` in the final output if neither
  source has a plausible value for that quarter. Logs loudly on rejection
  (`code33_engine: %s period=%s implausible margin %.2f%% rejected...`) — ticker, period,
  and the computed margin.
- **Known limitation, stated plainly:** the log line does **not** include raw NI/revenue,
  only the already-computed percentage — `secfs_net_margin.py`/`edgar_net_margin.py`'s
  return dicts don't carry the raw dollar components alongside `net_margin_pct`, only the
  final ratio, so they aren't available to log at this ingestion point. If deeper
  diagnostics are ever needed, the raw values would need to be threaded through those two
  functions' return shape — not done here, kept to the ticketed scope.
- **Verification (minimal, per this commit's own scope — full automated regression
  intentionally skipped; user is verifying manually via ticker-by-ticker testing instead):**
  syntax/import check clean; TRT's real `-0.23%` (the exact value Commit 1 fixed) confirmed
  to pass through untouched, no rejection logged; `get_code33_data()` runs without error for
  MU (status `green`, margins in a normal range) as a second smoke check.

**4-commit sequence complete** (`8f620c4` → `64a5757` → `9753f34` → this commit): unit-
conversion bug fixed at the source, the endpoint routed through the engine's own
date-aware gap detection, a third-leg fallback added for gaps no SEC-sourced tool can
fill, and a plausibility guard added as a last line of defense against the same bug class
recurring silently.

### Newest-quarter-missing bug — edgar_revenue.py / edgar_net_margin.py open-fiscal-year gap
- **Commit:** `9c421c5` (2026-07-09)
- **What it was:** A ticker's newest already-filed quarter silently never reached output
  whenever that quarter belonged to a still-open fiscal year (no closing 10-K filed yet).
- **Root cause:** The quarter-assembly loop's only iteration driver was the list of
  already-filed 10-Ks — for each one, it scanned already-fetched 10-Qs for quarters strictly
  between that 10-K's period-end and the previous 10-K's (`prev_fye < period < fye`). A
  quarter filed *after* the latest 10-K had no window in that loop to land in at all. The
  quarter was extracted successfully from its own 10-Q — the bug was purely in assembly, not
  extraction.
- **How found:** Confirmed live on NVDA, AMD, and MSFT — each missing its newest
  already-filed quarter for exactly this reason.
- **How fixed:** Added an additive second pass — the strict complement (`period > latest_fye`)
  — that surfaces up to 3 such quarters directly from the already-fetched quarter pool. Never
  attempts Q4 derivation in the open year (no annual filing exists yet to derive from). Purely
  additive: 61 insertions, 0 deletions across both files; none of the 9 pre-existing hardcoded
  bug-fixes in either file were touched.
- **Verification:** NVDA/AMD (1 quarter open) and MSFT (3 quarters open, the real
  multi-quarter case) all correctly surfaced; AMD/MSFT cross-checked against Macrotrends
  independently (exact match); ORCL (fiscal year just closed, 0 quarters open) correctly
  returns nothing, no phantom entries; MU's dramatic Q2/Q3 FY2026 jump ($23.8B → $41.5B)
  verified real against Micron's own press release, not a bug. Regression-tested clean
  against 11 already-working tickers. **Re-verified live again 2026-07-11** during an
  unrelated investigation (NVDA reproduction for the double-merge bug below): newest quarter
  2026-04-26 confirmed present in `get_code33_data("NVDA")`'s output.
- **Note:** CLAUDE.md's IN PROGRESS section listed this as "pending explicit go-ahead, not
  yet implemented" for two days after it actually shipped — corrected 2026-07-11.

### sec_edgar.py cache-removal regression — SEC rate-limit cascade
- **Commit:** `f3faf5a` (2026-07-10) — caught before shipping, not a released regression
- **What it was:** During a cleanup pass, removing `@st.cache_data` from
  `sec_edgar.py::_get_ticker_mapping()` (a zero-arg function fetching SEC's full multi-MB
  ticker→CIK map) turned a one-fetch-per-process call into a one-fetch-per-ticker call.
- **Root cause:** `get_cik()` — called on every single ticker lookup by
  `secfs_net_margin.py`, `secfs_revenue.py`, `preflight_checks.py`, and
  `watchlist_ticker_audit.py` — calls `_get_ticker_mapping()` every time. With the decorator,
  one process-lifetime fetch was reused across an entire batch; without it, a 16-ticker
  verification run refetched the file 16x back-to-back and mid-run degraded into
  rate-limit/timeout failures.
- **How found:** Post-change regression verification (re-ran the same 16-ticker baseline
  capture used throughout this period) — 11 of 16 tickers (LIN, JNJ, CB, AME, BLK, NVDA, AMD,
  MSFT, AIP, CELH, plus a partial hit on CMP) collapsed to fully `insufficient` results.
  Caught during the verification step of the same session that introduced it — never
  committed or shipped in the broken state.
- **How fixed:** Replaced the removed decorator with `functools.lru_cache(maxsize=1)` —
  same one-fetch-per-process effect, no streamlit dependency. Judged appropriate specifically
  for this function: SEC's ticker→CIK map has no meaningful staleness risk within a process
  lifetime, unlike `code33_engine.py`'s 24h result cache (see next entry) where a bare
  removal was correct instead.
- **Verification:** Re-ran the identical 16-ticker capture post-fix — all previously-collapsed
  tickers matched the original baseline exactly (LIN, BLK, NVDA, AMD, MSFT, AIP, CELH
  byte-identical). Also boot-tested the FastAPI server end-to-end (`GET /api/ticker/MU` over
  real HTTP, 200 OK, server stopped cleanly) and ran the test suite (6 passed, 1 xfailed,
  unchanged from documented baseline).

### Dead st.cache_data decorators / stale CACHE_VERSION staleness risk
- **Commit:** `f3faf5a` (2026-07-10)
- **What it was:** `code33_engine.py::get_code33_data()` carried `@st.cache_data(ttl=86400)`;
  `sec_edgar.py` carried 4 more `@st.cache_data` decorators. Both leftover from a
  pre-FastAPI Streamlit architecture — no Streamlit runtime exists anymore (confirmed: every
  call triggers a "No runtime found, using MemoryCacheStorageManager" warning), so these were
  silently caching in-memory per long-running FastAPI server process, with no way to bust the
  cache short of a full restart.
- **Root cause / confirmed real risk:** `CACHE_VERSION` (the cache key's version component)
  was **not bumped** across the 4 most recent NI/revenue logic fix commits (`5f680ae`,
  `9c421c5`, `186d24d`, `8d455cf`) — none of them touch `code33_engine.py`. A long-running
  server left running across any of those deploys could have kept serving pre-fix cached
  numbers for up to 24h post-deploy.
- **How found:** Pre-check grep for `"streamlit"` (case-insensitive) across the live
  codebase, run ahead of a user-confirmed cleanup pass — found it wasn't just
  `code33_engine.py`; `sec_edgar.py` had 4 more instances. Cross-referenced `CACHE_VERSION`'s
  bump history via `git log` to confirm the staleness-window claim.
- **How fixed:** Removed `import streamlit as st` and the decorator from
  `code33_engine.py` (pure removal, no replacement — FastAPI doesn't need it). Removed 3 of
  `sec_edgar.py`'s 4 decorators the same way (`get_recent_filings`, `get_insider_filings`,
  `get_key_filings` — confirmed zero callers anywhere in the live codebase). The 4th
  (`_get_ticker_mapping`) needed a real replacement, not a bare removal — see the regression
  entry above.
- **Verification:** Server boot test (clean start, no import errors), live HTTP endpoint test
  (200 OK, full data returned), test suite (6 passed, 1 xfailed), full 16-ticker regression
  re-verification.

---

## Solution prepared, not yet implemented

> **Section note (2026-08-01): the one item below is OBSOLETE, not pending.** Every file it
> names (`secfs_revenue.py`, `secfs_net_margin.py`, `code33_engine.py`) was deleted in the
> 2026-07-22 engine swap, so it describes a pipeline that no longer exists. Kept for the
> diagnosis only. CLAUDE.md already carries this caveat; recorded here so the section header
> does not read as a live to-do.

### Count-gate double-merge redundancy
- **Found:** 2026-07-11, during META manual testing (`get_code33_data("META")` took 70.1s —
  over the expected budget).
- **What it is:** `secfs_revenue.py`/`secfs_net_margin.py`'s inner secfsdstools→edgartools
  fallback gates on `len(merged) >= n_quarters` — a pure count, with **zero recency check**.
  So it wrongly skips calling edgartools whenever secfsdstools already has ≥16 *old* quarters,
  even when the single newest expected quarter specifically is missing — which is the normal
  steady state, since the local secfsdstools bulk dataset lags live filings by ~1 quarter by
  design (documented in the module's own docstring).
- **Why it's not (currently) a correctness bug:** `code33_engine.py` runs its own, separate,
  date-aware target-quarter check (`_target_quarter_ends`/`_fill_target_quarters`) and
  re-fetches via edgartools itself whenever it finds the gap the inner layer missed — and that
  outer call succeeds, because it runs through the already-fixed `edgar_revenue.py`/
  `edgar_net_margin.py` (see "Newest-quarter-missing bug" above). Confirmed live on NVDA,
  right now: inner layer logs "16/16 secfsdstools quarters — skipping edgartools" (wrong,
  missing 2026-04-26); outer layer catches it and logs "rev source =
  secfsdstools+EDGAR-edgartools, missing = []" (correct); final output includes 2026-04-26.
  Verified this is a **separate, unrelated mechanism** from the already-fixed 07-07/`9c421c5`
  bug — different files, different pipeline layer (`git show 9c421c5 --stat` confirms
  `secfs_revenue.py`/`secfs_net_margin.py` were untouched by that commit, then or since).
- **Real cost:** ~19-33s of live edgartools latency per metric, per affected ticker, on every
  uncached call — purely from redundant work, not from any single call being duplicated
  (the inner layer never actually calls edgartools in the failing case; it just wrongly thinks
  it doesn't need to, and the outer layer ends up doing 100% of the real work anyway).
- **Blast radius:** Hits 13 of 16 tracked regression tickers — GOOGL, CMP, LIN, JNJ, CB, AME,
  NVDA, AMD, MSFT, AIP, CELH, PED, TEAM. Only MU, CPTP, and BLK's NI leg escape it (their local
  secfsdstools coverage happens to already include the newest quarter, or never accumulates
  ≥16 quarters in the first place so the inner layer's count-gate correctly falls through to
  edgartools on its own). This is the common case for mature, long-filing tickers, not an edge
  case.
- **Proposed plan (not implemented):** Give the inner fallback's skip decision the same
  recency-awareness `code33_engine.py` already has — e.g. check whether the newest entry
  already in `merged` is within the same ~45-day filing-lag tolerance of today, instead of
  just counting quarters. Once the inner layer reliably closes this gap itself, delete
  `code33_engine.py`'s now-redundant outer retry blocks (the `_rev_missing_precheck`/
  `_npm_missing_precheck` → second edgartools call pattern), keeping
  `_fill_target_quarters` only for its other job (final windowing/alignment against the
  target dates).
- **Status:** Investigated and planned across three separate sessions (2026-07-11); no code
  changed. Pending a decision to implement.

---

## No solution yet / open

*(None currently — the one item that was here is closed out below.)*

### TRT margin output not re-verified under the new NI-tag priority order — RESOLVED
**Closed out 2026-07-12** — the "next step" this item asked for (run TRT through the engine,
cross-check against its own filings) was done as part of investigating a different, more
urgent TRT symptom (a -230,303% margin). Result: TRT's NI *tag selection* was never the
problem — the extracted value exact-matched TRT's real filed net income ($-38,000). The
actual defect was the unrelated `_to_m()` unit-conversion bug (see Resolved section above).
Background/status kept for the record:
- TRT carries a `NetIncomeLossAvailableToCommonStockholdersBasic` tag, same as CELH — but for
  TRT that tag nets out non-controlling interest, not preferred dividends (TRT has no
  preferred stock, confirmed directly against its balance sheet). Same XBRL tag, different
  economic adjustment underneath it. This is fine — the tag choice was never wrong.
- An earlier, separate concern (duplicate/ambiguous rows under this tag) was investigated and
  cleared previously: a throwaway diagnostic script bug (missing XBRL `ddate` filter), not a
  production issue — `_own_period_value` already pins on `ddate` correctly.

---

## Verified clean, no issues found

Tickers manually tested and confirmed correct during this period, for context:

- **MU** — Q4 FY2024 net income derivation cross-checked directly against real SEC EDGAR
  10-K/10-Q filings (bypassing the secfsdstools/edgartools abstraction entirely). Engine's
  Q1+Q2+Q3+derived-Q4 arithmetic confirmed correct: $887M, matching the Macrotrends-implied
  figure ($888M) within rounding. Investigated 2026-07-10.
- **META** — Engine-side output (last 8 quarters revenue/NI/margin, sources, raw XBRL tag
  trace) and Macrotrends-side TTM data both pulled and manually cross-checked line by line;
  no discrepancies found (aside from the separate, already-documented count-gate performance
  issue above, which affects latency, not correctness, for META). Investigated 2026-07-11.
- **XOM** — Verified clean during this period.

---

## Open — found 2026-07-31, 10-ticker data-accuracy pass (v31-code33-screener)

Scope: raw per-quarter output read off the live backend (`GET /api/ticker/{T}` →
`get_code33_data(t, CACHE_VERSION)`, n_quarters=8 default) for UNP, MU, INTC, JBLU, LMND,
IQV, SHOP, CRSP, ORA, SOFI. All 10 returned HTTP 200, no exceptions. Numbers were eyeballed
for plausibility only — **no Macrotrends/filing cross-check was performed this round**, so
every "suspected" item below needs filing-level confirmation before it's treated as proven.
No engine, adapter, or code33-screener code was touched.

### ORA — newest quarter revenue — CLEARED (downgraded 2026-07-31 from SUSPECTED, HIGH)
- **Resolution:** cross-verified against TradingView on 2026-07-31 — a separate data provider
  running a separate pipeline with no shared code, no shared source libraries, and no shared
  tag-priority logic with this engine. TradingView reports **$403.91M** for ORA's 2026-03-31
  quarter: the same figure the engine produced. Two independent extractions landing on the
  identical number is strong evidence this is Ormat's real reported revenue, not an artifact
  of the `...IncludingAssessedTax` tag the fill happened to resolve.
- **Not just the flagged quarter:** all 8 quarters matched TradingView exactly or
  near-exactly, so the series as a whole is consistent — which also removes the original
  concern that the secfsdstools history and the edgartools-filled newest quarter were being
  built from non-comparable revenue definitions. If they were, the join would show up as a
  discontinuity against a third source, and it doesn't.
- **Consequence for the +75.80% YoY:** it stands as real. The scale objection that drove the
  original flag (a quarter annualizing to ~$1.6B against a company doing ~$935M-1.0B/year)
  was reasoning from expected magnitude, and expected magnitude lost to two independent
  measurements agreeing.
- **Caveat — strongly supported, not airtight.** This was checked against TradingView, *not*
  against Ormat's own 10-Q. Both sources ultimately derive from the same SEC filing, so a
  shared upstream misread cannot be excluded on this evidence alone, however unlikely. Pulling
  the discrete 2026-03-31 revenue fact directly from the filing would fully close it. Left
  open as an optional last step, not a blocker.
- **Still worth knowing (unaffected by this clearing):** the observation that ORA's newest
  quarter filled under `RevenueFromContractWithCustomerIncludingAssessedTax` while every other
  ticker in the run filled under `...ExcludingAssessedTax` remains true and remains a real
  tag-consistency question for the general case. It just isn't producing a wrong number here.

**Original investigation notes — kept for history (the reasoning that produced the flag):**
- **Ticker/quarter:** ORA, period_end 2026-03-31.
- **What's wrong:** revenue comes back **$403.9M**, against $276.0M the prior quarter and
  $229.8M the year-ago quarter — a reported **+75.80% YoY**, far outside ORA's own recent
  range (+1.79% to +19.63% across the other seven quarters). Ormat's full-year 2025 revenue
  is roughly $935M-1.0B; $403.9M in a single quarter annualizes to ~$1.6B, which does not
  fit the company's scale.
- **Evidence pointing at a tag mismatch, not a real jump:** the server log shows this quarter
  was gap-filled from edgartools under
  `RevenueFromContractWithCustomerIncludingAssessedTax` — note **Including**. Every other
  ticker in this run filled under `...ExcludingAssessedTax` (or `Revenues`). If the seven
  secfsdstools-sourced quarters before it were built from a different tag, the series is
  joining two non-comparable revenue definitions at exactly the point the YoY is computed
  from, which would inflate the newest quarter and its YoY together.
- **Not confirmed:** the tag actually used for ORA's earlier seven quarters was not read this
  round, and the figure was not checked against Ormat's own 10-Q. Both are the next step.
- **Blast radius if real:** any ticker whose edgartools fill resolves a different revenue tag
  than its secfsdstools history — the newest quarter is *always* the edgartools-filled one
  (see the fiscal-label entry below), so this is the quarter every YoY and the entire Code 33
  signal depends on.

### Margin plausibility guard lost in the engine swap — CLOSED (downgraded 2026-08-01 from CONFIRMED, MEDIUM)
- **Resolution (2026-08-01, via `/investigate`): the CRSP numbers are REAL. Not a bug, and
  the proposed fix was wrong.** All 8 quarters were verified dollar-exact against
  `data.sec.gov` companyfacts (CIK 1674416, resolved from SEC's own ticker map, not
  hardcoded), bypassing secfsdstools and edgartools entirely. Net income matched to the
  dollar on all 8; margin recomputed by hand from SEC's filed figures matched the engine to
  two decimals on all 8. The flagged quarter is **2024-06-30**:
  `-126,408,000 / 517,000 x 100 = -24,450.29%`. The two calendar Q4s in the window
  (2024-12-31, 2025-12-31) are `derived_fy_minus_quarters` — both were independently
  back-solved from FY totals minus Q1+Q2+Q3 and also landed exactly. `ni_restated` is
  `false` on all 8, so no AES-style restatement discard is involved.
- **CRSP is near-zero-revenue, NOT pre-revenue** — a distinction that matters. Unlike the
  RVMD/XENE/SYRE/DNLI cluster (which file a revenue concept valued exactly `$0.00`, or no
  revenue tag at all), CRSP files real non-zero `RevenueFromContractWithCustomerExcludingAssessedTax`
  every quarter: **$0.5-1.5M**. Against that sits **$86M-$209M** of quarterly net loss from
  clinical-stage R&D. The ratio lands in the tens of thousands of percent as arithmetic, not
  error. CRSP correctly does NOT reach the `no reported revenue (pre-revenue company)` bucket,
  and its `red` status is computed on correct numbers.
- **Why the originally-proposed fix would have been wrong.** Porting `990bcba`'s ±1000%
  tripwire into the adapter as written would have **suppressed 7 of CRSP's 8 quarters — every
  one of them dollar-exact against SEC.** The guard was built for the TRT `_to_m()`
  unit-conversion bug, where the extreme value was *incorrect*. Here the extreme values are
  *correct*. A bare magnitude threshold cannot separate those two cases, because what makes
  TRT wrong is a broken unit conversion, not the size of the output.
- **If the guard is revisited later,** it needs to distinguish "extreme because the ratio is
  genuinely extreme" from "extreme because of a calculation bug" — e.g. by checking the
  inputs (revenue and NI each individually plausible against the company's own history and
  filed scale) rather than the ratio's magnitude. Flagged as a design constraint, not a
  queued task. Nothing is currently known to be producing wrong margins.
- **Scope of this clearing:** CRSP specifically, and the reasoning about magnitude thresholds
  generally. It does NOT re-verify any other ticker, and it does not claim the pipeline is
  incapable of producing a wrong margin — only that the CRSP evidence cited as proof of a
  defect was misread, and that the absence of a ±1000% guard is not itself a defect.

**Original investigation notes — kept for history (the reasoning that produced the flag):**
- **Ticker/quarters:** CRSP, all 8 quarters. Net margins returned: -24450.29%, -14276.08%,
  -104.54%, -15722.08%, -23379.93%, -11973.12%, -15117.25%, -8431.48%.
- **What's wrong:** these values are *arithmetically correct* — CRSP books tiny collaboration
  revenue ($517K-$1.5M in most quarters) against a real ~$100-200M quarterly net loss, so the
  ratio genuinely lands in the tens of thousands of percent. The bug is not the number, it's
  that **nothing stops a number like this any more**.
- **Root cause:** commit `990bcba` (2026-07-13) added `_is_plausible_margin()` in
  `code33_engine.py` — a deliberate ±1000% tripwire, the 4th and final commit of the TRT
  `-230,303%` sequence, explicitly built as defense-in-depth against a future
  scaling/extraction bug. `code33_engine.py` was deleted in the 2026-07-22 engine swap and
  **the guard was not ported into `utils/code33_adapter.py`**. Confirmed by reading the
  adapter (it takes `net_margin_pct` straight off each `MarginPoint`, no bound check) and by
  grepping code33-screener: its only plausibility logic (`_is_implausible_net_income` /
  `_is_implausible_revenue`) applies to **derived Q4 values only**, compares against sibling
  quarters rather than an absolute bound, and merely *flags* `.plausible` — it never rejects.
  The adapter also never reads `ni_plausible`/`revenue_plausible`, so even that flag is
  discarded before the API.
- **Consequence:** the exact bug class Commit `990bcba` was written to catch would now reach
  output silently. CRSP proves values past ±1000% flow through untouched today.
- **Note:** CRSP's Code 33 status (`red`) is being computed on these margins.

### Every ticker's newest quarter has a blank fiscal label — CLOSED (FIXED 2026-08-01)
- **Resolution (2026-08-01): fixed, together with the "Q4 renders as FY FY24" entry
  below.** The two were fixed as one change deliberately — repairing the blank label
  alone would have widened the FY-doubling bug, since a gap-filled quarter sourced from
  a 10-K row carries `fp='FY'` and would newly have rendered as `FY FY26`.
- **Root cause, corrected.** The original note below guessed the fix belonged upstream in
  code33-screener. It didn't. This was a **dropped field at a return boundary**, the same
  shape as the AES restatement discard: `code33/edgar_fill.py`'s `fetch_discrete_quarter()`
  declared a 5-tuple return `(period_end, value, tag, accession, filing_date)` and simply
  never handed fy/fp back — so `_fill_gaps` had nothing to pass and hardcoded `None`. The
  values were present all along, on the very row the function had already selected: the
  edgartools facts dataframe carries `fiscal_year` and `fiscal_period` columns.
- **Fix as applied** (3 files, in-repo per rule 1 — no upstream change needed):
  - `code33/edgar_fill.py`: return contract widened to a 7-tuple, adding
    `int(row["fiscal_year"])` / `str(row["fiscal_period"])`, each `pd.notna`-guarded and
    falling back to `None` so a missing value yields a blank label rather than a guess.
  - `code33/pipeline.py`: `_fill_gaps` unpacks the two new fields and passes `fy=fy, fp=fp`
    in place of the hardcoded `None, None`.
  - `utils/code33_adapter.py`: `_fq_label()` gains `_FP_ALIASES = {'FY': 'Q4'}` (see the
    entry below).
- **Why the fy/fp values are trustworthy:** `fetch_discrete_quarter` already selected the
  EARLIEST filing_date (the original as-filed figure, for restatement reasons). edgartools
  stamps every fact with its FILING's fiscal year/period, so a quarter's own original 10-Q
  labels it correctly, while comparative columns republished in later filings carry the
  later filing's fy/fp. The pre-existing earliest-filing rule avoids that mislabel by
  construction — confirmed live, where other concepts in the same window DO carry
  conflicting fp values across filings.
- **Verification:** before-baseline across 14 tickers had **14 blank labels and 25 doubled
  labels**; after the fix, **0 and 0**. **101 labels** were then checked against each
  company's real fiscal calendar, derived independently from SEC 10-K period ends (trusting
  neither edgartools' fiscal fields nor SEC's per-fact `fp` stamp) — **101 correct, 0 blank,
  0 mismatch**, including non-calendar fiscal years (FDS Aug FYE, COR Sep FYE, MU Aug FYE)
  and 52/53-week filers (INTC, MU), whose FY ends drift 2-4 days from the month-end `ddate`
  secfsdstools records. A **364-key byte-level payload comparison** across the same 14
  tickers showed **0 unintended changes** — the only differences are `rev_labels`/`npm_labels`
  on the 13 label-bearing tickers. Confirmed end-to-end over HTTP (`GET /api/ticker/FDS` →
  200, both filled quarters labelled `Q2 FY26` / `Q3 FY26`), single listener verified first.
- **Scope note — no visible UI change.** `rev_labels`/`npm_labels` have **zero consumers**:
  no references in `frontend/index.html`, `frontend/journal.html`, or `api/server.py`. This
  is API-payload correctness. Nothing a user sees today changes.
- **Not touched:** `pipeline.py`'s hardcoded `form="10-Q"` on filled points, which can be a
  10-K row. Same discard class, deliberately left as separate scope.

**Original investigation notes — kept for history (including the fix-location guess that
turned out to be wrong):**
- **Tickers/quarters:** all 9 non-bank tickers, newest quarter each — UNP 2026-03-31,
  MU 2026-05-28, INTC 2026-03-28, JBLU 2026-03-31, LMND 2026-03-31, IQV 2026-03-31,
  SHOP 2026-03-31, CRSP 2026-03-31, ORA 2026-03-31. 9 of 9, not an edge case.
- **What's wrong:** `rev_labels` is an empty string for that quarter while every older
  quarter carries one ("Q2 FY24" etc.).
- **Root cause:** `code33/pipeline.py` lines 95-96 construct every edgartools-filled
  `QuarterPoint` with `fy=None, fp=None` (the fill path has no fiscal-period metadata to
  copy). The adapter's `_fq_label()` returns `''` whenever either is None. Since the
  edgartools fill exists precisely to supply the quarter secfsdstools doesn't have yet, the
  blank label lands on the newest quarter **by construction, every time**.
- **Where the fix belongs:** the `fy`/`fp` gap is in code33-screener, which is off-limits from
  quant-terminal sessions per CLAUDE.md rule 1 — either fix it there under its own regression
  suite, or have `_fq_label()` derive a label from `period_end` when fy/fp are absent.

### Q4 renders as "FY FY24" instead of "Q4 FY24" — CLOSED (FIXED 2026-08-01)
- **Resolution (2026-08-01): fixed, together with the blank-label entry above.** Fixing
  the blank label alone would have made this one WORSE, not left it alone: a gap-filled
  quarter whose source row is a 10-K carries `fp='FY'`, so newly-labelled fills would have
  started rendering `FY FY26` too. The two had to move as one change.
- **Fix as applied:** `utils/code33_adapter.py`'s `_fq_label()` now maps `fp` through
  `_FP_ALIASES = {'FY': 'Q4'}` before formatting. One dict, one lookup.
- **Why `Q4` is the honest label, not a cosmetic relabel.** SEC's fiscal-period vocabulary
  has no `Q4` at all — a fiscal year's fourth quarter is only ever reported on the 10-K,
  which carries `fp='FY'`. The value attached to the point is always the discrete quarter
  (`derived_fy_minus_quarters` back-solves it as FY minus Q1+Q2+Q3), never the full year,
  so `FY FY24` actively misdescribed it. `Q4` also matches what the engine already assumes
  internally: `quarterly_engine._attach_plausibility()` groups siblings on
  `fp in ('Q1','Q2','Q3')` — it already treats `'FY'` as the Q4 slot. The fix makes the
  label agree with semantics the code was relying on anyway.
- **Verification:** 25 doubled labels across the 14-ticker baseline → **0** after. Covered
  by the same 101-label fiscal-calendar check and 364-key byte-level comparison recorded in
  the entry above; every former `FY FY24`/`FY FY25` now reads `Q4 FY24`/`Q4 FY25` and was
  confirmed correct against the company's real fiscal year end. `_fq_label` was also
  exercised directly across `Q1-Q4`, `FY`, `None`, `NaN` and an unknown `fp` — `None`/`NaN`
  still yield `''`, unknown values pass through unchanged.

**Original investigation notes — kept for history:**
- **Tickers/quarters:** every calendar-Q4 quarter across the run — e.g. UNP 2024-12-31 and
  2025-12-31, INTC 2024-12-31 and 2025-12-31, JBLU, IQV, LMND, CRSP, SHOP all show
  `FY FY24` / `FY FY25`. MU shows it on its own August fiscal year-ends (2024-08-31,
  2025-08-31), which is the same thing on a non-calendar FY.
- **What's wrong:** cosmetic only — the value attached to the label is the correct discrete
  quarter, not a full-year figure. SEC reports `fp='FY'` on the 10-K row the Q4 figure is
  derived from, and `_fq_label()` passes it straight through, so a single quarter is labelled
  as if it were the whole year.

### Revenue series is fetched twice per ticker — CLOSED (fixed by `b7d6b6a`, confirmed 2026-08-01)
- **Resolution:** fixed by commit `b7d6b6a` ("adapter: expose discarded per-quarter data,
  drop duplicate revenue build"), which made `_get_code33_data_inner()` reuse the already-built
  `rev_series` instead of calling `get_complete_net_margin()`, which rebuilt the same series
  (including repeating its live-EDGAR fill) from scratch. That commit predates this session and
  is already on origin/main; this entry was simply never updated.
- **Verified 2026-08-01, not assumed:** instrumented the pipeline logger and counted
  `(quarter, tag)` fill pairs per ticker. MU and IQV each show 2 fills — one revenue-tag, one
  net-income-tag, for the same quarter — and **zero duplicate (quarter, tag) pairs**. The
  original symptom was the SAME quarter filled twice under the revenue tag; that no longer
  happens. (A ticker can legitimately show two revenue fills for two DIFFERENT quarters, which
  is the gap-filler working, not the bug.)
- **What it is:** the server log shows each ticker's edgartools revenue gap-fill running
  **twice** before the net-income fill runs once — e.g. UNP 2026-03-31 filled from edgartools
  under `RevenueFromContractWithCustomerExcludingAssessedTax` at 08:46:54 and again at
  08:46:57, then `NetIncomeLoss` at 08:47:10. Same doubled pattern on all 9 non-bank tickers.
- **Mechanism:** `_get_code33_data_inner()` calls `get_complete_revenue_series()` directly,
  and then `get_complete_net_margin()` builds its own revenue leg internally to pair against
  NI — so the same series, including its live-EDGAR fill, is built twice per call.
- **Cost, not correctness:** both builds produce the same values. Same class as the
  already-tracked "Count-gate double-merge redundancy" above — wasted live-EDGAR latency, no
  wrong output.

### Not bugs — checked and cleared this round
- **SOFI `excluded_bank`** — correct. Log shows bank tags `NoninterestIncome`,
  `RevenuesNetOfInterestExpense`; SoFi holds a national bank charter.
- **SHOP `insufficient` on 5 quarters** — correct, and correctly labelled ("only 5 quarters of
  revenue filings - 7+ needed to form 3 year-over-year pairs"). Shopify converted from foreign
  private issuer (40-F) to domestic 10-Q filing in 2025; log confirms `quarter ~2024-12-31
  missing from both sources`. This is the same SDRL/INDV pattern already flagged in CLAUDE.md
  — mechanically "short history", but the cause is a filing-form conversion, not a young
  company.
- **INTC Q3 FY24 margin -125.26%** — real. $16.6B net loss on $13.3B revenue matches Intel's
  reported Q3 2024 impairment/restructuring quarter.
- **MU 2026-02-28 → 2026-05-28 revenue $23.86B → $41.46B** — the revenue leg of this jump was
  already verified real against Micron's own press release (see the 2026-07-09 entry). The
  **68.13% net margin** on the newest quarter was *not* part of that verification and is
  unusually high for a memory manufacturer even in an up-cycle — worth a filing check next
  round, listed here as unverified rather than as a bug.
- **No missing margins anywhere** — every revenue quarter paired to a margin within the
  25-day tolerance on all 9 non-bank tickers (`n_rev == n_npm`). No nulls, no unmatched dates.

### LMND revenue vs TradingView — NOT AN ENGINE DEFECT, engine matches SEC exactly
- **Investigated:** 2026-07-31, read-only. Premise checked: our revenue reads $16-33M higher
  than TradingView on all 8 quarters with the gap widening, while derived Net Income matches
  TradingView exactly — suggesting revenue as root cause.
- **Result: the engine's revenue is right.** Pulled LMND's facts straight from
  `data.sec.gov/api/xbrl/companyfacts` (CIK 1691421), bypassing secfsdstools and edgartools
  entirely. The engine's number is a **dollar-exact match to LMND's own filed `Revenues`
  fact** on every quarter checkable:

  | Quarter | Engine | SEC `Revenues` (10-Q) | Match |
  |---|---|---|---|
  | 2024-06-30 | $122,000,000 | $122,000,000 (adsh 0001691421-24-000108) | exact |
  | 2025-09-30 | $194,500,000 | $194,500,000 (adsh 0001691421-25-000149) | exact |
  | 2026-03-31 | $258,000,000 | $258,000,000 (adsh 0001691421-26-000034) | exact |

- **Tag selection is consistent, not switching.** `python -m code33.revenue LMND` (the module's
  own read-only diagnostic) shows **all 8 quarters resolved under the single tag `Revenues`** —
  the first entry in `REVENUE_TAGS` (`code33-screener/src/code33/revenue.py:14-25`). No tag
  drift across the series, and the edgartools-filled newest quarter used `Revenues` too
  (confirmed in the earlier run's server log). The 2024-12-31 and 2025-12-31 points are
  `derived_fy_minus_quarters` (FY minus Q1+Q2+Q3), both flagged `plausible=True`.
- **No over-broad tag is being summed.** The gross-premium hypothesis was checked and ruled
  out directly: LMND does file `PremiumsWrittenGross` ($343,900,000 for 2026-03-31 — far above
  our $258.0M) and `PremiumsEarnedNet` ($212,600,000 — below it). Neither is being read. The
  engine sums nothing; it reads one reported fact per quarter.
- **Where the difference with TradingView most likely comes from — definitional, on
  TradingView's side.** `Revenues` is LMND's *total* revenue line. Its components for the
  quarters checked:

  | Quarter | Total `Revenues` | `NetInvestmentIncome` | `InsuranceCommissionsAndFees` | `PremiumsEarnedNet` |
  |---|---|---|---|---|
  | 2024-06-30 | $122.0M | $8.1M | $8.1M | $89.3M |
  | 2025-09-30 | $194.5M | $9.7M | $12.6M | $140.0M |
  | 2026-03-31 | $258.0M | $9.8M | $12.0M | $212.6M |

  Stripping investment income + commission/fee income yields gaps of $16.2M / $22.3M / $21.8M
  — the lower half of the reported $16-33M range, and growing over time as those two lines
  grow, which fits the described pattern. It does not account for the $33M upper end, so the
  exact TradingView line item is **not pinned down**.
- **Open question, needs input:** TradingView's own per-quarter revenue figures were not
  available this session, so which line it reports could not be identified conclusively. With
  those 8 numbers the component table above should isolate it immediately.
- **Consistent with Net Income matching:** NI is unaffected by any revenue-definition choice,
  which is exactly why it agrees while revenue doesn't. That pattern points at a definitional
  mismatch between vendors, not at a data defect on either side.

### Two premises in the LMND investigation request that did not hold
- **There is no OSCR entry in this file.** Grepped the whole quant-terminal repo (excluding the
  bundled frontend HTML) and all of code33-screener for `OSCR` — zero matches. No
  insurance-sector wrong-revenue-tag bug has been logged here for OSCR or any other ticker, so
  the requested "same root cause as OSCR?" comparison had nothing to compare against. If that
  bug was found, it was recorded somewhere other than `bug_report.md`.
- **There is no `_REV_TAGS` symbol anywhere.** Zero matches in either repo. The revenue
  priority list is `REVENUE_TAGS` in `code33-screener/src/code33/revenue.py`, and unlike the
  deleted in-repo engine's private `_NI_TAGS`, it lives in the external project.

---

## 2026-08-01 — dual-class ticker handling at the yfinance boundary

### BRK.B returned HTTP 500 from /api/ticker — FIXED
- **Ticker:** BRK.B (any dual-class ticker using dot notation — BRK.B, MOG.A, etc.).
- **Symptom:** `GET /api/ticker/BRK.B` returned **500** with body
  `{"error":"'exchangeTimezoneName'"}`. Found during the vendoring regression pass, where
  BRK.B was included specifically to exercise `normalize_ticker()`.
- **Root cause:** `api/server.py` passed the **un-normalized** ticker straight to
  `yf.Ticker(t)`, where `t = ticker.upper()` — so Yahoo received `"BRK.B"`. Yahoo uses SEC's
  hyphen form (`BRK-B`), the same form `normalize_ticker()` already produces and that the
  engine half of the same request had *already applied* successfully. With an unrecognised
  symbol, yfinance's `fast_info` had no metadata and raised
  `KeyError: 'exchangeTimezoneName'` on first attribute access.
- **Why the existing guards didn't catch it:** every access was written as
  `getattr(info, 'last_price', 0)`. `getattr`'s default only absorbs **AttributeError** —
  `fast_info` is a lazy dict that raises **KeyError**, so the default never fired and the
  error escaped to the bare `except Exception` at the end of the handler, which converted it
  into a 500. One missing quote field took down the entire response, including the complete
  and correct Code 33 payload sitting next to it.
- **Confirmed before fixing, not inferred:** ran both symbols through yfinance directly —
  `BRK.B` → `fast_info.last_price` raises `KeyError: 'exchangeTimezoneName'`;
  `BRK-B` → returns `511.54` and `"Berkshire Hathaway Inc. New"`.
- **Fix (api/server.py only):** `yf.Ticker(normalize_ticker(t))` at the call site, reusing
  the adapter's existing function rather than duplicating the dot→hyphen rule; plus a local
  `fi()` wrapper around every `fast_info` read (and a try/except around `tk.info`) so a
  genuinely absent field degrades to its existing default instead of 500ing. Attribute
  resolution order, fallback values and `None` semantics all preserved deliberately — the
  guard is additive, not a behaviour change.
- **Verified:** BRK.B now returns **200** with a full payload — price 511.54, market cap
  1.1T, PE 15.17, 8 quarters, revenue $94.97B/$94.23B/$93.68B, net income
  $30.80B/$19.20B/$10.11B, mixed `reported`/`derived_fy_minus_quarters`/`edgartools`
  provenance. **Independent confirmation the cause was fixed rather than suppressed:**
  yfinance's own `$BRK.B: possibly delisted; no price data found` errors, present 4x on
  every prior run, are now **completely absent** — Yahoo resolves the symbol.
- **Regression:** UNP, MU, AES, ORA, SHOP, SOFI re-pulled against the last verified state —
  entire payload compared minus live market fields, **156 key comparisons, 0 differences**.
  Server logs clean, single listener verified.

### Same bug class at four other endpoints — CLOSED (FIXED 2026-08-01)
- **Resolution (2026-08-01): all 6 remaining call sites now normalize.** Every
  `yf.Ticker(...)` in `api/server.py` routes through `normalize_ticker()`; a grep for an
  un-normalized one returns nothing. Same one-line pattern as the original `/api/ticker`
  fix, applied per call site with its own before/after check rather than as a blanket edit.
- **The "unconfirmed impact" above is now confirmed, and it was NOT uniform.** Each
  endpoint was tested against BRK.B on the un-fixed code first. The failure modes differ,
  which is why they were checked individually:

  | Endpoint | BRK.B before | BRK.B after | Verdict |
  |---|---|---|---|
  | `/api/chart` | **HTTP 404** `{"error":"No data"}` (19 B) | 200, 251 price points, 472.84 → 511.54 | **FIXED** |
  | `/api/financials` | 200 but `balance_sheet:{}`, `cash_flow:{}`, all valuation `null` (1,347 B) | 200, 46 BS keys, 48 CF keys, P/E 15.22 (16,402 B) | **FIXED** |
  | `/api/peers` | 200, `peers:[]` (29 B) | 200, JPM/BAC/GS/MS via Financial Services (358 B) | **FIXED** |
  | `/api/news` | 200, **real Berkshire headlines** (3,314 B) | 3,314 B, unchanged | **was never broken** |
  | `/api/ownership` | `{"institutional":[],"insiders":[]}` | unchanged, still empty | **normalized, but a DIFFERENT bug keeps it empty** |

- **`/api/news` was never actually broken.** tradingview-scraper is the primary source and
  resolves BRK.B fine; the yfinance call is a fallback that only runs when the earlier
  sources return nothing, so the latent fault was never reached. Normalized anyway —
  the call site carried the same bug, it just wasn't being exercised.
- **`/api/ownership` — normalization was correct but is NOT sufficient. Separate open
  defect, see below.** At the yfinance layer the dot-ticker fault is real and confirmed:
  `BRK-B` returns 10 institutional + 36 insider rows, `BRK.B` returns an empty frame. But
  the endpoint returns `{"institutional":[],"insiders":[]}` for **normal tickers too**
  (AAPL), so something else is failing. Ruled out by direct test: yfinance has the data
  (AAPL → 10 institutional + 78 insider rows), and the endpoint's own parsing body,
  run verbatim in a fresh process, succeeds and produces real rows
  (`Blackrock Inc. 7.8%`, `BORDERS BEN / Jun 16 / 34,236 / BUY`). It only fails inside the
  server process. The bare `except Exception` at the end of the handler returns the empty
  payload and logs nothing, so the actual cause is invisible. **Not fixed — out of scope
  for the normalization pass. First step for whoever picks it up: log the exception
  instead of swallowing it.**
- **Regression:** AAPL through all 5 endpoints is **byte-identical** before and after
  (`cmp` on the raw response bodies — chart, financials, news, ownership, peers). The
  server was restarted between captures specifically so `TICKER_CACHE` could not serve a
  pre-fix result. Response `ticker` fields still echo the app's canonical dot form
  (`"ticker":"BRK.B"`) — only the outbound yfinance symbol is normalized.
- **Adjacent, deliberately not touched:** `api/server.py`'s peer self-exclusion compares
  `p != ticker.upper()` against a hardcoded peer list. For a dot ticker neither `BRK.B` nor
  `BRK-B` appears in those lists, so it is a no-op today, not a live fault.

**Original investigation notes — kept for history (the pattern was right; the per-endpoint
impact was assumed uniform and is not):**
- **What:** `/api/ticker` was the only endpoint fixed. Every other yfinance call site still
  passes the raw, un-normalized ticker. Confirmed by reading the code (the *pattern* is
  verified; the runtime impact is **not** — none of these were actually called with a
  dual-class ticker):

  | Endpoint | Line | Call |
  |---|---|---|
  | `/api/chart/{ticker}` | 623 | `yf.Ticker(t).history(...)` — `t = ticker.upper()` (612) |
  | `/api/financials/{ticker}` | 656 | `yf.Ticker(t)` — `t = ticker.upper()` (647) |
  | `/api/news/{ticker}` | 922 | `yf.Ticker(t)` — `t = ticker.upper()` (860) |
  | `/api/ownership/{ticker}` | 998 | `yf.Ticker(ticker.upper())` |
  | `/api/peers/{ticker}` | 1039, 1042 | `yf.Ticker(ticker.upper())` x2 |

  Only `api/server.py:550` (`/api/ticker`) normalizes.
- **Expected practical impact:** a dual-class ticker now shows correct core stats but would
  still have a blank chart, and possibly missing news, ownership and peer data — a partially
  broken analysis page rather than an obvious failure. Whether each endpoint 500s, returns
  empty, or degrades silently depends on how each handles yfinance's empty response; the
  `fi()`-style KeyError trap added to `/api/ticker` exists at none of them.
- **Severity:** LOW/MEDIUM pending confirmation. Low reach (only dot-notation tickers, and
  the watchlist that carried BRK.B was deleted 2026-08-01), but silent partial failure is
  worse to diagnose than a clean 500.
- **Not fixed, not verified — flagged for a future pass.** The fix would likely be the same
  one-line `normalize_ticker()` reuse at each call site, but each endpoint needs its own
  before/after check rather than a blanket edit.

### /api/ownership returns empty for EVERY ticker — CLOSED (FIXED 2026-08-02, commit `ac227c7`)
- **Resolution: real holders are served again.** `GET /api/ownership/AAPL` returns a
  populated payload (`Blackrock Inc. 7.8%`, `Vanguard Capital Management LLC 6.5%`,
  `State Street Corporation 4.1%`) instead of `{"institutional":[],"insiders":[]}`.
  Re-confirmed over HTTP against the running server on 2026-08-02, single listener on
  8000 verified first.
- **Root cause — yfinance's cached auth token going stale and never revalidating.**
  yfinance holds a process-wide `YfData` singleton; `_get_crumb_basic()` returns the
  cached crumb whenever it is not `None` and never revalidates it. Once Yahoo rejects
  that crumb, every crumb-authenticated call fails for the remaining life of the
  process. This is exactly why the handler's own logic succeeded when copied into a
  fresh Python process (see the original notes below) while the identical code returned
  nothing inside the long-running uvicorn worker — the leading suspect recorded at the
  time ("a poisoned yfinance session in the uvicorn worker") was correct, and the
  mechanism is now named.
- **Why it was silent.** `scrapers/holders.py` and `scrapers/quote.py` both absorb the
  resulting `HTTPError` into empty results, because `YfConfig.debug.hide_exceptions`
  defaults to `True`. The endpoint therefore returned an empty payload behind a **200**,
  with nothing raised for the handler's own `except` to report. Chart and price kept
  working throughout because the chart API needs no crumb — which is what made the
  failure look ticker-agnostic-but-endpoint-specific.
- **Fix (`api/server.py`):** `_yf_force_fresh_crumb()` drops the cached cookie/crumb, and
  `_yf_quote_summary()` retries once with a **new** `yf.Ticker` instance — necessary
  because yfinance memoizes the parsed result on the instance, so retrying on the old
  object returns the same failure. Wired into `/api/ownership`, `/api/ticker` (company
  name, P/E), `/api/financials` (valuation block) and `/api/peers` (sector lookup).
- **Two co-fixes, each of which produced the identical empty-ownership symptom on its own:**
  1. **`.info` raises on a stale crumb rather than degrading.** Unguarded, it escaped
     `/api/financials` entirely, costing the balance sheet and cash flow as well as the
     valuation block.
  2. **NaN insider values crashed JSON serialization.** AAPL's insider rows carry
     `Value=NaN`; `float('nan')` is not JSON-compliant, so `JSONResponse` raised and the
     handler's `except` returned the empty payload — a second, independent path to the
     same symptom.
- **Frontend, same commit:** `_applyToD` only overwrote `D.owners` on a non-empty
  response, so a hardcoded mock holder list (Vanguard 8.42%, BlackRock 7.13%, Fidelity
  4.88%, State Street 3.94%, T. Rowe Price 2.21%) rendered as if it were live data for
  every ticker. Literals removed outright; an explicit "Ownership data unavailable" state
  renders instead, and an empty response now clears the previous ticker's holders.
- **Verified against a deliberately poisoned crumb:** AAPL/MSFT/KO all return real
  holders where the pre-fix code returns 0 rows for all three; company name, P/E,
  valuation and peer list all recover; chart output byte-identical, since that path never
  used the crumb.
- **Not to be confused with `8d2af72`** (`perf(api): cache /api/peers and /api/ownership`),
  the very next commit. That one is a caching layer only and fixes nothing here — it
  deliberately refuses to cache an empty ownership payload *because* of this bug, since a
  transient failure is indistinguishable from a company with no 13F/Form 4 rows.

**Original investigation notes (2026-08-01) — kept for history, superseded by the
resolution above:**
- **Symptom:** `GET /api/ownership/{any}` returns `{"institutional":[],"insiders":[]}`.
  Reproduced on AAPL and BRK.B. Not a dual-class issue — it affects all tickers.
- **Found incidentally** while confirming per-endpoint failure modes for the
  ticker-normalization pass above. That pass fixed the endpoint's dot-ticker fault
  (real and confirmed at the yfinance layer), which is necessary but not sufficient here.
- **The data exists and the code works in isolation — ruled out, not assumed:**
  - yfinance has it: AAPL → `institutional_holders` 10 rows, `insider_transactions` 78
    rows. BRK-B → 10 and 36 rows.
  - The handler's parsing body, copied verbatim and run in a fresh Python process against
    AAPL, succeeds and produces real output: `Blackrock Inc. 7.8%`,
    `Vanguard Capital Management LLC 6.5%`, insider `BORDERS BEN / Jun 16 / 34,236 / BUY`.
  - Column names are current: `institutional_holders` has `pctHeld`, `Holder`;
    `insider_transactions` has `Value`, `Insider`, `Start Date`. The `Relationship` lookup
    returns `None`, which `str()` absorbs — not the failure.
- **So the fault is specific to the server process**, not the logic or the upstream data.
  A poisoned/rate-limited yfinance session in the uvicorn worker is the leading suspect,
  unproven.
- **Why it is invisible:** the handler ends in a bare `except Exception as e:` that returns
  the empty payload and logs nothing at all. The real error has never been seen.
- **First step for whoever picks this up:** log the exception in that handler instead of
  swallowing it, then re-request. Everything else is guesswork until that line exists.

---

## 2026-08-01 — corporate actions inside a single CIK

### GE — YoY compares post-spinoff against pre-spinoff, producing a ~-43% artifact — CLOSED (FIXED 2026-08-02)
- **Resolution: YoY is now computed on the filer's own recast basis.** GE reports
  +5.81% / +14.34% / +10.94% for the three affected quarters instead of
  -43.26% / -44.33% / -38.11%. Confirmed over HTTP after restart.
- **No boundary detection was needed — the signal already existed.** Both candidate
  signals from the plan were investigated and rejected: GE files
  `IncomeLossFromDiscontinuedOperationsNetOfTax` on essentially every quarter back to
  2017 (±$50M residue from decades of divestitures, no signal), and a revenue
  step-change heuristic repeats the ±1000%-margin-guard mistake closed earlier —
  a magnitude threshold cannot separate a divestiture from a volatile quarter.
  What works instead: **GE recast its own history**, and `_attach_restatement_flags`
  in `code33/quarterly_engine.py` already detected it, on the revenue leg, all along.
  `restated=True` lands on exactly the five pre-spinoff quarters and `False` on every
  post-spinoff one — the boundary delineated by the filer, not inferred by us.
- **Fix (`utils/code33_adapter.py` only — `code33/` untouched):**
  - New `_yoy_value(point)`: returns `restated_value` when the filer republished the
    quarter, else `value`. Applied to **both ends** of every comparison so the two
    sides stay on one basis.
  - `yoy_for()` routes both `cur` and `prior` through it.
  - `_yoy_miss_cause()` routes its falsy-base test through it too. Its docstring
    promises it "mirrors yoy_for's walk exactly … so the diagnosis can never disagree
    with the number actually emitted"; changing one without the other would have let a
    quarter with `value=0` but a non-zero `restated_value` compute a real YoY while the
    diagnosis still reported `zero_base`.
  - `rev_restated` / `rev_restated_value` exposed — computed upstream and discarded
    until now, the same discard class as the `ni_restated` fix.
  - The displayed `rev` array is unchanged and stays as-filed. Only the comparison moves.
- **Scope, measured on the full universe (543 tickers, 389s):** 496 have no restated
  revenue quarter at all, 22 restate <10%, **23 restate ≥10%**. GE is only 6th —
  DBRG (92.6%), ROIV (90.2%), PRSU (86.4%), STRZ (63.4%) and CALY (55.3%) are worse,
  and **JNJ** (15.7%, Kenvue) and **NVRI** (17.1%) are affected. Restatements run in
  **both directions** — DBD and NVRI recast *upward* — which is a second reason a
  "revenue dropped sharply" heuristic could never have worked.
- **Verification:**
  - **57 restated quarters across all 23 material tickers verified EXACT against
    `data.sec.gov`** — engine `.value` == SEC earliest-filed, engine `.restated_value`
    == SEC latest-filed, on every one.
  - **Universe-wide old-vs-new audit, 430 scored tickers, 0 errors:** 36 rev_yoy
    changed, **1 status changed**, 394 untouched. **Zero tickers with no restated
    quarter changed in any way** — containment proven, not assumed.
  - 30-ticker clean control sample drawn only from the 496 scan-confirmed clean:
    **all 30 byte-identical**.
- **The one status change: PAG yellow → red, accepted as correct.** PAG's restatement is
  small (4.83%) but it has 6 restated quarters and its YoY sat near a Code 33 boundary,
  so ±5pp crossed it. Deliberately NOT special-cased: status sensitivity depends on where
  a YoY sits relative to the thresholds, not on the size of the restatement, so any
  "ignore small restatements" rule would be arbitrary and would reintroduce the
  magnitude-heuristic error this fix exists to avoid.
- **Pre-existing issue found while verifying, NOT fixed and NOT caused by this change:**
  **DBD** emerged from Chapter 11 on 2023-08-11, so its Q3 2023 is split into a 41-day
  predecessor and a 49-day successor stub. The engine treats the 49-day stub
  (`2023-08-12→2023-09-30`) as a quarter. Both its as-filed 591,800,000 and its recast
  895,400,000 are real SEC facts for that exact period, so the restatement handling is
  correct — but a 49-day stub is not comparable to a 90-day quarter either way. Separate
  data-quality question about fresh-start accounting, worth its own look.

**Original investigation notes — kept for history:**
- **Ticker/quarters:** GE (GE Aerospace, CIK 40545), the three oldest displayed quarters
  2024-09-30, 2024-12-31, 2025-03-31.
- **Every revenue and net-income VALUE is correct.** Verified dollar-exact against
  `data.sec.gov` companyfacts, as-filed, on all 8 quarters. This is not a data-extraction
  defect. The defect is in what the derived YoY *means*.
- **What's wrong.** GE completed the GE Vernova spinoff on 2024-04-02. The adapter pulls
  `n_quarters + 4 = 12` quarters so every displayed quarter has a year-ago base, and those
  extra bases reach back **across the spinoff boundary**. So the three oldest displayed
  quarters compare standalone GE Aerospace against the old consolidated GE:

  | Displayed quarter | Revenue (post-spinoff) | YoY base (pre-spinoff) | Reported YoY |
  |---|---|---|---|
  | 2024-09-30 | 9,842,000,000 | 2023-09-30 → 17,346,000,000 | **-43.26%** |
  | 2024-12-31 | 10,812,000,000 | 2023-12-31 → 19,423,000,000 | **-44.33%** |
  | 2025-03-31 | 9,935,000,000 | 2024-03-31 → 16,053,000,000 | **-38.11%** |
  | 2025-06-30 | 11,023,000,000 | 2024-06-30 → 9,094,000,000 (post-spinoff) | +21.21% |

  The scale break is visible in SEC's own as-filed series: 2024-03-31 = 16,053,000,000, then
  2024-06-30 = 9,094,000,000 the very next quarter. GE did not shrink 43%; it divested a
  business. From 2025-06-30 onward both sides of the comparison are post-spinoff and the YoY
  flips to the real ~+21%.
- **Consequence.** Code 33 is a revenue-*acceleration* screener, so a spinoff manufactures a
  severe fake deceleration followed by a fake acceleration. Nothing in the payload flags it —
  `rev_sources` reads `reported` on every one of these quarters, because each individual value
  genuinely is.
- **Not affecting GE's status today, but it did.** The current 3-quarter window is
  +17.61 / +24.73 / +21.10, all clean post-spinoff comparisons, so today's `red` is computed
  on valid data. A scan run in late 2024 or early 2025, when the -43% quarters were newest,
  would have scored GE on the artifact.
- **Scope, measured not assumed.** Scanned all 10 tickers in this pull for the signature
  (large YoY swing + sign flip). GE is the only hit: swing 69.06pp with a clean break between
  the third and fourth quarter. TSLA (37.30pp) and CAT (32.03pp) have comparable swings but
  no structural break — those are ordinary business cycles, correctly reported.
- **Relationship to the XOM/NVRI finding.** Same family — a corporate action breaking series
  continuity — but a different mechanism, and the XOM fix does not help here. XOM was a
  *ticker→CIK* discontinuity (history on a different CIK). GE is a *comparability*
  discontinuity **within one CIK**: the CIK is correct, the history is present and correctly
  extracted, and the values either side of the boundary are simply not comparable.
- **Not fixed, and the fix is not obvious.** Detecting it means identifying a spinoff/
  divestiture boundary. Candidate signals: a large step change in revenue scale against a
  filing that reports discontinued operations, or SEC's own `IncomeLossFromDiscontinuedOperations*`
  concepts appearing in the boundary filings. Suppressing YoY across such a boundary would be
  more honest than reporting a number that reads as a business decline. Flagged for a decision,
  not queued as work.

---

## 2026-08-01 — ticker→CIK resolution after a holdco reorganization

### XOM returned no data because SEC moved the ticker to a new CIK — CLOSED (FIXED 2026-08-01)
- **Symptom:** `XOM` returned `status='insufficient'`, `no 10-Q/10-K filings found`, with the
  company name showing as "ExxonMobil Holdings Corporation".
- **NOT an engine defect. A real corporate event.** ExxonMobil completed a holding-company
  reorganization in July 2026. SEC's `company_tickers.json` — the authoritative ticker→CIK
  map, and the one the engine correctly follows — now contains exactly one XOM entry:
  `{"cik_str": 2115436, "ticker": "XOM", "title": "ExxonMobil Holdings Corp"}`. The engine
  resolved it faithfully. The lookup code, its data source, and its one-week cache were all
  verified correct and current.
- **The two entities, confirmed at `data.sec.gov`:**

  | | CIK 2115436 (resolved) | CIK 34088 (has the history) |
  |---|---|---|
  | Name | ExxonMobil Holdings Corp | EXXON MOBIL CORP |
  | Ticker / exchange | XOM / NYSE | XOM / NYSE |
  | SIC | 2911 Petroleum Refining | 2911 Petroleum Refining |
  | Total filings | 27 | 1001 |
  | 10-K / 10-Q | **0 / 0** | 7 / 19 |
  | Filing range | 2026-07-01 → 2026-07-31 | 2019-12-11 → 2026-07-06 |
  | Form signature | `8-K12B`, `S-8 POS`, `POSASR` | 10-K, 10-Q, 8-K, S-4, 425 |

  `8-K12B` is the successor-issuer registration form — the signature of a holdco reorg.
- **Also affected: NVRI.** Enviri Corp (CIK 2104052) registered via `10-12B`; its history is
  on Harsco, **CIK 45876** (confirmed via EDGAR company search).
- **Blast radius: 2 of 541, not the 39 initially flagged.** A universe scan found 39 tickers
  whose resolved CIK has no local 10-K/10-Q, and 36 with none at SEC either. Testing the form
  signature rather than assuming they shared a cause split them cleanly:

  | Group | Count | Signature | Status |
  |---|---|---|---|
  | Holdco/successor reorg | **2** | `8-K12B` / `10-12B` | the actual bug (XOM, NVRI) |
  | Foreign private issuers | ~33 | `6-K`, `20-F` | out of scope by design, never file 10-Qs |
  | Funds / trusts / local gaps | 3 | `N-Q`, `NPORT-P`, or absent locally | out of scope |

  SBLK, FRO, TX, MANU, VIK, TBBB, STNG, NMM, TEN, DHT, ZGN, OPRA, BAP and the rest were
  correctly reporting no data and must not be swept into the predecessor path.
- **Fix 1 — `code33/ticker_lookup.py`:** a `PREDECESSOR_CIK` map (XOM→34088, NVRI→45876)
  consulted before the SEC lookup. Explicit and auditable rather than a heuristic, precisely
  so the 36 out-of-scope tickers cannot be caught by it.
  **BRIDGE, NOT PERMANENT — recorded in the code comment.** It works today because the
  successor has filed no 10-Q yet, and because the edgartools gap-fill leg resolves by
  TICKER (not CIK) and returns a unified view across the reorg (verified: 3,819 fact rows
  through 2026-03-31). Re-check when ExxonMobil Holdings files its first 10-Q, expected
  ~November 2026; at that point the correct series may span both CIKs.
- **Fix 2 — `code33/quarterly_engine.py`, restores detection lost in the swap.** The
  zero-filings path emitted one generic message, which is why a July-2026 holdco reorg looked
  identical to a Greek shipping company that has never filed a 10-Q. It now re-queries the
  index without the form filter and distinguishes:
  - no filings of ANY kind → names corporate reorganization as a likely cause and points at
    `PREDECESSOR_CIK`;
  - filings present but no 10-K/10-Q → names the actual forms (`20-F`/`6-K`) and the
    annual-only foreign-issuer cause.

  This is the signal `check_cik_discontinuity` provided in `tools/preflight_checks.py`
  (built for the BLK holdco reorg) before `dc77f59` deleted it on 2026-07-22 — reported
  inline on the failing path rather than as a separate preflight pass. The
  `no 10-Q/10-K filings found` prefix is retained deliberately so `_classify_failure`'s
  bucketing in `api/server.py` is unchanged.
- **Verification:**
  - XOM: 0 → **8 quarters**, newest 2026-03-31 revenue **$85,138,000,000**, dollar-exact
    against SEC. NVRI: 0 → **8 quarters**, newest **$549,803,000**, dollar-exact.
  - **36 zero-filing controls: zero gained data, zero CIK changes, zero status changes.**
    Their `excluded_reason` text did change, which is Fix 2's entire purpose — 33 now report
    the foreign-issuer cause, 3 the no-filings-of-any-kind cause.
  - AAPL / DELL / WMT byte-identical.
  - Fix 2's message paths exercised directly on all three shapes including a synthetic
    nonexistent CIK.
  - Confirmed over HTTP after restart, single listener verified.
- **Known imprecision, flagged not fixed:** HQL, PBT and RMT (funds/trusts, and one local
  dataset gap) land in the no-filings-of-any-kind branch and therefore see a message that
  mentions reorganization as a possibility. The wording is conditional ("if a corporate
  reorganization recently moved this ticker"), so it does not assert one, but it is not a
  precise description of their situation.
- **Note:** `company_name` still shows "ExxonMobil Holdings Corporation" — that comes from
  yfinance and is correct, since that IS the listed entity. Only the fundamentals are read
  from the predecessor.

---

## Open — found 2026-07-31, second 10-ticker data-accuracy pass (v31-code33-screener)

Scope: AES, ICE, FDS, ESRT, SLXN, PLTR, NUE, DKNG, NET, U, same method as the first pass
(`GET /api/ticker/{T}`, n_quarters=8 default, live backend, per-quarter source attributed from
server logs). All 10 returned HTTP 200, no exceptions, 2-49s each. Unlike the first pass, the
suspicious items here **were** checked against SEC ground truth (`data.sec.gov` companyfacts,
direct HTTP, bypassing secfsdstools and edgartools). No engine, adapter, or code33-screener
code was touched.

**Revenue extraction was exact on all 9 non-SLXN tickers.** Every newest-quarter revenue
figure matched the company's own filed 10-Q fact to the dollar: AES $3,180,000,000 ·
ICE $3,666,000,000 · FDS $622,918,000 · ESRT $190,325,000 · PLTR $1,632,583,000 ·
NUE $9,496,000,000 · DKNG $1,646,076,000 · NET $639,755,000 · U $508,238,000.

### ICE — an already-filed quarter is missing from output — CLOSED (FIXED 2026-08-01)
- **Resolution (2026-08-01): fixed, and it was never an ICE problem — it hit ~99% of the
  universe every quarter.**
- **How the mechanism actually worked.** `FILING_LAG_DAYS = 45` had exactly ONE consumer
  (`expected_quarter_ends`) with exactly ONE call site (`_fill_gaps`), and it gated ONLY the
  forward-projection loop. Quarters the bulk dataset already has were never filtered by it
  (proven: a `known_end` 32 days old survives the cutoff; the same date as a *projection*
  is blocked). Critically, **there is no overdue/missing determination anywhere in the
  codebase** — `missing` is a local variable driving fetch attempts, a failed fetch logs and
  `continue`s, and status is computed downstream from points that exist. So the "protection
  for late filers" the buffer appeared to provide did not exist, which is what made the fix
  safe.
- **Why 45 was wrong for this job.** 45 is the SEC 10-Q statutory *deadline* (40 days for
  accelerated filers, 45 for non-accelerated/smaller reporting companies) — the LATEST a
  quarter may legally appear. It was being used to answer a different question: when should
  we START looking. Measured across **17,635 10-Q filings / 499 tickers** from the local
  filing index: **96.6% are filed before day 45**, median lag **36 days**, fastest **9 days**
  (DAL). **494 of 499 companies (99.0%)** had their most recent 10-Q filed inside the old
  gate, so nearly every company carried a blind window every quarter, of width
  `45 - actual_lag`. ICE's was 15 days; DAL's is 36.
- **Fix as applied** (`code33/pipeline.py` only):
  - `FILING_LAG_DAYS` renamed to `SEC_10Q_DEADLINE_DAYS = 45`, retained as a documented
    reference constant and **no longer used to gate anything**.
  - New `PROJECTION_MIN_AGE_DAYS = 10`, below the fastest observed filer, now drives the
    cutoff. Safe because a projection that finds nothing costs one filter over an
    already-cached facts frame and adds NO point — `fetch_discrete_quarter` returns `None`
    and `_fill_gaps` continues.
  - **Second bug, found during the investigation and fixed with it:**
    `return (projections + known_sorted)[:quarters]` let every added projection evict the
    OLDEST known end from the fill window. An evicted end whose value is `None` is a real
    gap that then silently stops being back-filled — and those oldest quarters are the
    year-ago YoY bases (the adapter pulls `n_quarters + 4` for exactly that reason). Now
    `return projections + known_sorted[:quarters]`, additive. Harmless to return a longer
    list: `expected` only drives fill attempts, never output length.
- **Verification** (18 tickers, in-process, before/after):
  - **7 tickers gained their true newest quarter**, every one verified dollar-exact against
    `data.sec.gov`: ICE 2026-06-30 $3,611,000,000 (filed 2026-07-30) · DAL $19,757,000,000 ·
    CSX $3,935,000,000 · TRV $12,153,000,000 · JNJ 2026-06-28 $25,310,000,000 ·
    WAB $3,179,000,000 · AAPL 2026-06-27 $109,417,000,000 (filed 2026-07-31, one day before
    the run — it would have stayed invisible until 2026-08-11).
  - **11 tickers fully unchanged**, including every late/at-deadline filer that reaches the
    pipeline (PACS, FEIM, CGON) and the non-calendar-quarter names whose next quarter genuinely
    is not filed yet (PANW, FDX, DELL, WMT). Note the universe contains only 5 companies whose
    newest 10-Q was filed at/after day 45, and 2 of those (NUTX, AVBC) are banks that exit at
    the `excluded_bank` gate before the pipeline runs.
  - **Fix 2 confirmed by its own test cases:** GLUE and PTGX, the two tickers whose OLDEST
    pulled quarter is a fillable gap, are byte-identical, and their fill attempts ROSE
    (4→6 and 2→4) — the older gaps are still being targeted, which is exactly what the old
    eviction would have stopped.
  - **Zero violations.** No existing value changed anywhere; no YoY base went null (null-YoY
    count 0→0 on all 7 gainers). The 7 gainers do drop their oldest quarter, which is the
    fixed-size window (`merged[:quarters]`) sliding forward by one — series length stays
    exactly 12, displayed stays exactly 8. That is normal quarterly behaviour, not eviction.
  - **Measured cost, not assumed:** EDGAR fill attempts across the set 26 → 41 (+15, one extra
    speculative lookup per ticker that gains a projection). Wall-clock **91.8s → 93.1s across
    18 tickers (+1.3s total, ~0.07s/ticker)** — the extra lookup filters an already-cached
    facts frame rather than fetching again.
  - Confirmed end-to-end over HTTP (`GET /api/ticker/ICE` → 200: newest 2026-06-30, `Q2 FY26`,
    $3,611,000,000), single listener verified before and after restart.

**Original investigation notes — kept for history:**
- **Ticker/quarter:** ICE, period_end **2026-06-30**, absent entirely.
- **What's wrong:** the engine's newest quarter for ICE is 2026-03-31. ICE's 2026-06-30 quarter
  was **filed 2026-07-30 — the day before this run** — and is present in SEC's companyfacts
  under `RevenueFromContractWithCustomerExcludingAssessedTax` at **$3,611,000,000** (net income
  $958,000,000). The engine never requested it, so it never appeared as a gap for edgartools to
  fill; the server log shows only a 2026-03-31 fill for ICE.
- **Mechanism:** `expected_quarter_ends()` targets a quarter only once the filing-lag buffer
  (~45 days past period end) has elapsed — 2026-06-30 + 45 days = 2026-08-14. Between a
  company's actual filing date and that computed due date there is a blind window in which an
  already-public quarter is invisible to the engine. For ICE that window is ~15 days wide.
- **Why this matters more than it looks:** the newest quarter is the one every YoY comparison
  and the entire Code 33 acceleration signal keys on. A ticker scanned inside its own blind
  window is scored on stale data with no indication anything is missing.
- **Relationship to existing notes:** this is the same mechanism previously observed on MU and
  recorded (in the `9753f34` entry above) as "not a bug; will self-resolve once the quarter is
  due." That reading was based on the quarter not yet existing. ICE shows the case where the
  quarter **does** exist, is filed, is public, and is still skipped — which is a different and
  worse situation than the one that assessment covered.
- **Scope check:** the other 8 tickers are current — their newest filed 10-Q quarter is exactly
  the one the engine returned. So this fires only for companies that file early relative to the
  buffer, not universally.

### SLXN — pre-revenue company never reaches the pre-revenue diagnosis — CLOSED (FIXED 2026-08-01)
- **Resolution (2026-08-01): fixed in `utils/code33_adapter.py`. The original root-cause
  analysis below was correct; the blast radius was not — this was never about SLXN alone.**
- **Scale, measured not assumed: 16 tickers, not 1.** Scanned the 41 revenue-history-ish
  failures from the 540-ticker checkpoint (30 `insufficient revenue history` + 11
  `insufficient (unspecified)`) plus SLXN against `data.sec.gov` companyconcept across all
  nine of code33's `REVENUE_TAGS`. **16 file no revenue concept at all** — SLXN DFTX BCAX
  ERAS SION APGE KOD EWTX ANRO IMVT MBX ELVN TRVI LBRX TECX CLYM. 2 file `$0.00` only
  (ORKA, APA — already correctly bucketed) and 24 file real revenue (genuinely short
  history). 15 of the 16 sit inside the 540 universe, so that scan's pre-revenue bucket
  **undercounted by ~15** while `insufficient revenue history` over-counted by the same —
  roughly 37% of the revenue-history failures on that scan.
- **Provenance of the omission:** `dc77f59` (engine swap) introduced the `<5` guard;
  `60aac70` added `_diagnose_insufficient` and wired it into exactly ONE call site.
  `git show 60aac70^` vs `60aac70` shows the guard line byte-identical. That commit's
  message is "name the cause on **every** insufficient path" — this path was missed. Not a
  design decision, an omission.
- **Fix as applied** (one file, `utils/code33_adapter.py`; `api/server.py` deliberately
  untouched):
  - Three helpers — `_blank_revenue_count()`, `_is_pre_revenue()`, `_pre_revenue_reason()` —
    so the guard and `_diagnose_insufficient`'s check #1 share one definition of the rule and
    cannot drift (same discipline as `_yoy_miss_cause` mirroring `yoy_for`).
  - Check #1 collapsed onto the helpers. Same condition, same string, no behavior change.
  - The `<5` guard gained ONE conditional, testing **`rev_series.points`** (the UNFILTERED
    series — the filter is exactly what hides the evidence). Only the pre-revenue case is
    rerouted; every other short-history reason returns its existing message verbatim.
  - `_diagnose_insufficient` is deliberately NOT called from the guard, even though check #1
    would return first. Calling `_pre_revenue_reason` directly removes a silent dependency on
    check ordering.
- **`api/server.py` needed no change** and got none. The new message contains
  `"no reported revenue"` and contains neither `"usable revenue quarters"` (line 302) nor
  `"quarters of revenue filings"` (line 320), so it falls through to line 312 and buckets
  itself as `no reported revenue (pre-revenue company)`.
- **Verification:** 26-ticker before/after, engine run in-process. **All 16 flipped** from
  `insufficient revenue history` to `no reported revenue (pre-revenue company)`, each with a
  real count (`no reported revenue in N of N quarters ...`) — verified individually, not
  sampled. **702 key comparisons, 0 violations**; the only changes are `excluded_reason`,
  the `sources` dict `_empty_result` derives from it, and the derived bucket, on those 16
  only. Controls byte-identical on every field: RVMD XENE SYRE DNLI PLSE (the `$0.00`
  cluster — they never reach the guard), SDRL INDV (short history, real revenue), and
  AAPL/DELL/WMT (unrelated; still red/green/red). Confirmed end-to-end over HTTP
  (`GET /api/ticker/SLXN` → 200), single listener verified before and after restart.
- **Known softness, flagged not fixed:** the predicate is a ratio, so a ticker with very few
  pulled quarters can satisfy "at least half blank" on a small sample — LBRX resolves on
  `2 of 2`, SION on `4 of 4`. Both are genuinely pre-revenue (the SEC scan confirms zero
  revenue concepts across their entire filing history), so no wrong call today, but the
  predicate alone would be thin evidence on a 2-quarter ticker. A minimum-points floor is
  the obvious hardening if this ever misfires.

**Original investigation notes — kept for history (root cause correct, scale understated):**
- **Ticker:** SLXN (Silexion Therapeutics Corp, CIK 2022416), all quarters.
- **What's wrong:** SLXN returns `status='insufficient'` with
  `excluded_reason='only 0 usable revenue quarters'` — the generic count message — when it is a
  textbook instance of the `no reported revenue (pre-revenue company)` bucket added in the
  `insufficient-reason-labels` work merged earlier today.
- **Confirmed pre-revenue, not a data gap:** SEC companyfacts shows SLXN files **179 us-gaap
  concepts and not one revenue concept** (the only near-match is `InterestRevenueExpenseNet`).
  It is clinical-stage — R&D expense and net loss are filed every quarter (2026-03-31:
  NI -$2,733,000, R&D $1,370,000), revenue never is. Log confirms all 8 target quarters
  `missing from both sources`.
- **Root cause:** `_get_code33_data_inner()` returns early at the `len(rev_points) < 5` guard,
  which fires **before** `_diagnose_insufficient()` is ever called — that function only runs on
  the success path, after `_c33_status()`. So the split is:
  - files a revenue line valued $0.00 → point exists with `value=0` → survives to the diagnosis
    → correctly bucketed as pre-revenue (RVMD/DNLI/SYRE behave this way).
  - files **no revenue tag at all** → `value=None` → filtered out → early return → generic
    message, never bucketed.
  Both are the same real-world condition, reported two different ways depending on an XBRL
  tagging choice the company made.
- **Consequence:** the pre-revenue bucket undercounts, and the circuit breaker gets a generic
  cause it can't group on — the exact problem that work set out to fix, still present on one
  side of the split.

### FDS — the blank-label bug now confirmed on more than one quarter per ticker — CLOSED (FIXED 2026-08-01)
- **Resolution:** closed by the same fix as its parent entry ("Every ticker's newest quarter
  has a blank fiscal label"), which carries the full root cause and verification. FDS was
  the hardest case in the verification set and is now correct on both quarters:
  2026-02-28 → `Q2 FY26`, 2026-05-31 → `Q3 FY26`, checked against FactSet's real Aug-31
  fiscal year end and confirmed end-to-end over HTTP.
- **Ticker/quarters:** FDS, **2026-02-28 and 2026-05-31** — the two newest quarters, both with
  an empty `rev_labels` entry.
- **Extends the existing entry above** ("Every ticker's newest quarter has a blank fiscal
  label"). That entry described it as hitting the single newest quarter. FDS shows the count is
  really "however many quarters the edgartools fill supplied" — its August fiscal year-end
  leaves secfsdstools two quarters behind, so two fills happen and two labels come back blank.
  Same root cause (`pipeline.py:95-96` sets `fy=None, fp=None` on filled points); the blast
  radius is just wider than first written.

### AES net margin vs TradingView — two separate causes, one of them a real defect
Investigated 2026-07-31, read-only, against `data.sec.gov` companyfacts (CIK 874761) plus the
pipeline's own restatement flags. **Tag selection was ruled out first: the engine reads
`NetIncomeLoss` on all 12 quarters, never switching.** This is not an ORA-style problem. Two
unrelated effects stack, and they explain the inconsistent gap exactly.

#### Cause 1 — engine serves the originally-filed value after a restatement, and drops the flag that says so — DISCARD FIXED (`b7d6b6a`); value policy OPEN by design
- **Status split, 2026-08-01.** This entry bundles a defect and a policy question. Its own
  "Note on scope" below already separates them; the header did not, which left CLAUDE.md
  carrying "the restatement discard" as an open confirmed defect long after it was fixed.
  - **The discard — FIXED.** `b7d6b6a` stopped the adapter throwing the flags away.
    Verified live on AES: `ni_restated = [True, True, False×6]` with
    `ni_restated_value = [276000000.0, 504000000.0, ...]` on 2024-06-30 / 2024-09-30,
    exactly the two quarters named below. Callers can now see that a quarter was revised.
    That commit predates this session and is already on origin/main.
  - **Which value to serve — OPEN, and deliberately so.** The engine still emits the
    as-first-filed figure (`ni` = 185,000,000 for 2024-06-30, against the restated
    276,000,000). As the scope note says, this entry does not assume as-filed or as-restated
    is correct. It is a policy decision for the owner, **not an unfixed defect**, and it
    should not be carried in a confirmed-defects list.
- **Ticker/quarters:** AES, **2024-06-30** and **2024-09-30**.
- **What's wrong:** AES recast both quarters in later filings. The engine emits the figure as
  first reported and gives no indication it has been superseded:

  | Quarter | Engine emits (as first filed) | AES's own later figure | Filed in |
  |---|---|---|---|
  | 2024-06-30 | $185,000,000 | **$276,000,000** | 10-K 2025-03-11, restated again in FY2025 Q2 10-Q 2025-08-01 |
  | 2024-09-30 | $502,000,000 | **$504,000,000** | 10-K 2025-03-11 |

- **The pipeline already knows.** `get_quarterly_net_income_series(874761, 12)` returns those
  two points with **`restated=True` and `restated_value` populated** ($276,000,000 /
  $504,000,000) — every other quarter is `restated=False`. `_attach_restatement_flags()` in
  `quarterly_engine.py` detects this correctly and `MarginPoint` carries it through as
  `ni_restated` / `ni_restated_value`.
- **Root cause:** `utils/code33_adapter.py` reads only `net_margin_pct` off each `MarginPoint`
  and discards `ni_restated`/`ni_restated_value` (same discard that loses `net_income` and
  `ni_plausible`). So the engine holds the corrected number in memory and serves the stale one,
  with no flag reaching the API for anything downstream to act on.
- **Size of the error:** AES 2024-06-30 margin is served as **6.29%**; on AES's own restated
  net income it is **9.38%** — a **3.1 percentage point** error on a quarter that feeds the
  net-margin-expansion leg of the Code 33 signal directly. 2024-09-30 is minor (15.26% vs
  15.32%).
- **Why it matters beyond one ticker:** Code 33 compares quarters against each other. Mixing
  restated and non-restated quarters inside one 8-quarter window creates margin deltas that
  never happened. AES has 2 restated quarters inside its window right now.
- **Note on scope:** *which* value to serve (as-filed vs as-restated) is a legitimate policy
  choice and this entry does not assume one. What is unambiguous is that the restatement flag
  is computed, carried to the adapter boundary, and thrown away — so no caller can even see
  that a quarter was revised.

#### Cause 2 — TradingView uses a narrower net-income concept — CLEARED (definitional, LMND pattern)
- **What it is:** TradingView's AES figures match a concept that is not in `NI_TAGS` at all:
  **`NetIncomeLossFromContinuingOperationsAvailableToCommonShareholdersBasic`** — income from
  *continuing operations*, *available to common*. Both reported TradingView numbers were located
  in AES's filings exactly:

  | Quarter | TradingView | SEC concept it matches, to the dollar |
  |---|---|---|
  | 2025-09-30 | $671.00M | `NetIncomeLossFromContinuingOperationsAvailableToCommonShareholdersBasic` = $671,000,000 (10-Q filed 2025-11-04) |
  | 2024-06-30 | $282.00M | `NetIncomeLossAvailableToCommonStockholdersBasic` = $282,000,000 (10-Q filed 2025-08-01) |

- Engine reads `NetIncomeLoss` (total, parent-attributable). For 2025-09-30 that is
  $639,000,000 against TradingView's $671,000,000 — a **$32M pure definitional gap, no
  restatement involved that quarter**.

#### Why the gap is inconsistent — the two causes are independent and don't co-occur
| Quarter | Engine | Restated? | Definitional gap? | Result vs TradingView |
|---|---|---|---|---|
| 2024-06-30 | $185.1M | **yes** (→$276M) | yes (→$282M) | **worst case, ~$97M** — both stack |
| 2025-09-30 | $639.0M | no | **yes** (→$671M) | ~$32M, definition only |
| 2025-03-31 | $45.9M | no | no separate concept filed | **near-exact match** |
| 2024-12-31 | $560.1M (derived) | no | — | **near-exact match** |

The $97M worst case decomposes cleanly: **$91M restatement + $6M definition**. 2025-03-31
matched because AES neither restated it nor filed a separate continuing-ops/available-to-common
fact for it — every definition collapses to the same $46M.

#### The non-controlling-interest theory is ruled out
NCI size is irrelevant here, which is why the $119M-NCI quarter (2025-03-31) still matched. The
engine reads `NetIncomeLoss`, which is **already parent-attributable — NCI is excluded before
the engine ever sees it**. The NCI-inclusive concept is `ProfitLoss` (2025-03-31: **-$73M**,
2024-06-30: **-$39M**), and it sits third in `NI_TAGS`, behind `NetIncomeLoss`, so it is never
selected for AES. A gap that scaled with NCI would require the engine to be reading `ProfitLoss`,
and it never does.

### COR (Cencora) derived Q4 quarters — CLEARED, the numbers are real
Investigated 2026-07-31, read-only, against `data.sec.gov` companyfacts (CIK 1140859).
Flagged because COR's six *reported* quarters all sit at $400-700M net income while its two
*derived* quarters (`derived_fy_minus_quarters`) came back at $3,382,000 (2024-09-30, 0.00%
margin) and **-$339,704,000** (2025-09-30, -0.41%). Cencora's fiscal year ends in September,
so both are Q4s. **Not a calculation error — Cencora's real Q4 GAAP results are that bad.**

- **The derivation is arithmetically exact.** FY total minus Q1+Q2+Q3, every input matching
  SEC to the dollar:

  | | FY2024 (ends 2024-09-30) | FY2025 (ends 2025-09-30) |
  |---|---|---|
  | FY total (10-K) | $1,509.1M | $1,554.2M |
  | Q1 | $601.5M (2023-12-31) | $488.6M (2024-12-31) |
  | Q2 | $420.8M (2024-03-31) | $717.9M (2025-03-31) |
  | Q3 | $483.5M (2024-06-30) | $687.4M (2025-06-30) |
  | **Derived Q4** | **$3.4M** | **-$339.7M** |
  | Engine emitted | $3,382,000 | -$339,704,000 |

- **Independently confirmed by Cencora's own filed nine-month subtotal**, which the engine
  never touches — so this is a genuine second source on the same arithmetic, not the same sum
  computed twice. FY2024: filed 9-month NI (2023-10-01→2024-06-30) = **$1,505.7M** against a
  $1,509.1M full year, leaving $3.4M for Q4. FY2025: filed 9-month = **$1,893.9M** against a
  $1,554.2M full year — the company earned *more* in nine months than in twelve, which only
  happens if Q4 was a loss.
- **The cause is real charges landing almost entirely in Q4.** `GoodwillImpairmentLoss` is
  **$418.0M for FY2024 and $723.9M for FY2025 in the 10-K, and absent from both nine-month
  10-Q figures** — meaning essentially the whole impairment fell in the July-September quarter
  both years. FY2025 also carries $837.4M `AssetImpairmentCharges` and $229.4M
  `RestructuringCharges` annually, again with nothing comparable in the nine-month view. A
  ~$400-700M quarter absorbing a $418M / $724M impairment lands exactly where the engine put
  it: near zero, then negative.
- **Tag selection is consistent, ruled out.** COR resolves under `NetIncomeLoss` on every
  quarter and on both FY totals — no switching, and not `ProfitLoss` (which runs $2-5M higher
  per quarter: 2024-06-30 is $487.6M under `ProfitLoss` vs the $483.5M the engine used).
- **The derived-Q4 plausibility guard behaved correctly by not firing.**
  `_is_implausible_net_income` flags only when a derived value exceeds 4x the average magnitude
  of its sibling quarters — a ceiling of ~$2,008M (FY2024) and ~$2,525M (FY2025) here, which
  $3.4M and -$339.7M are nowhere near. Its docstring states the absence of a floor check is
  deliberate, because net income can legitimately sit near zero after a large quarter. That is
  precisely this case, so silence was the right behaviour, not a miss.
- **Worth knowing for screening, though it is not a defect:** COR's margin series swings
  0.85% → 0.00% → 0.60% → 0.95% purely because GAAP impairments concentrate in Q4. Code 33
  reads that as margin contraction and then expansion. The data is correct; the signal it
  produces on a company with a back-loaded charge cycle is still worth an eyeball before being
  treated as a real fundamental turn — same caution already recorded for AXON.

### Checked against SEC and cleared this round
- **ESRT (REIT) — exact match, no tag discontinuity.** The newest quarter's net income was
  filled under `NetIncomeLossAvailableToCommonStockholdersBasic` while every other ticker in
  the run used `NetIncomeLoss`, which looked like an ORA-style mid-series tag switch. It isn't:
  ESRT files **only** that tag and never plain `NetIncomeLoss`, so the series is internally
  consistent. Engine vs SEC, dollar-exact on every quarter — NI 2024-06-30 $17,071,000 /
  2024-09-30 $13,541,000 / 2025-03-31 $9,220,000 / 2025-06-30 $6,519,000 / 2025-09-30
  $7,985,000 / 2026-03-31 $1,235,000; revenue likewise exact. The margin collapse to **0.65%**
  on 2026-03-31 is real, not an artifact.
- **ICE revenue and net income — exact match.** 2026-03-31 revenue $3,666,000,000 and NI
  $1,413,000,000 both match the filed facts exactly. The 11pp margin jump to 38.54% is real.
- **NUE 2026-04-04 period end** — correct, not a date bug. Nucor uses 13-week fiscal quarters
  ending on a Saturday; SEC's own fact carries the same end date.

### Sector definition mismatches to expect when cross-checking against TradingView
Neither is an engine defect — both are the LMND pattern (engine reads the company's filed
total; a vendor may report a narrower line). Recording them so a TradingView delta on these
tickers isn't re-investigated as a bug:
- **ICE** — the engine reports ICE's **gross** revenue ($3.666B for 2026-03-31). ICE is widely
  quoted on "revenues less transaction-based expenses" (roughly $2.5B), which is a non-GAAP
  presentation — **ICE files no XBRL concept for it** (checked: no `transaction`-based or
  `revenue…less…` concept exists in its companyfacts). If TradingView shows ~$2.5B, that is a
  definitional difference, not a wrong read.
- **ESRT** — the engine's net income is the **common-stockholders** figure ($1,235,000 for
  2026-03-31), consistent with the CELH-era convention. ESRT also files `ProfitLoss`
  ($2,995,000 for the same quarter), which includes the operating-partnership non-controlling
  interests typical of an UPREIT. A vendor using `ProfitLoss` will show roughly 2.4x our net
  income and margin on this ticker.

### Reporting limits hit this round (engine contract, not defects)
- **Net Income is not available from the API.** `get_code33_data()` hardcodes `'ni': []`
  (intentional, per CLAUDE.md ENGINE STATUS). Upstream `MarginPoint` carries a real per-quarter
  `net_income`, but the adapter reads only `net_margin_pct` off it. Any NI figure in this
  round's table was **derived** as Revenue × Margin ÷ 100, not read from the engine.
- **Per-quarter data source is not available from the API.** `_src_summary()` collapses
  `QuarterPoint.source` into one `'+'`-joined set per series, so every ticker reports the same
  `derived_fy_minus_quarters+edgartools+reported` string with no way to attribute a specific
  quarter. Per-quarter provenance exists in the pipeline and is discarded at the adapter
  boundary. Server-log correlation was used instead to establish which quarter came from
  edgartools.

---

## 2026-08-04 — News Scanner Stage 1 build (new feature, isolated)

Three defects found and fixed during the build of `api/news_scanner.py`, plus one
pre-existing operational hazard confirmed. None of these touch the Code 33 engine,
`/api/news`, or any pre-existing endpoint — the feature is a separate universe by design.

### Finnhub API key written to the server log in plaintext — CLOSED (FIXED 2026-08-04)
- **Severity: security. Found by reading the log, not by inspection** — the key was already
  sitting in the log file at the time it was discovered.
- **Symptom:** every Finnhub network failure logged the full request URL, and
  `finnhub-python` passes the API key as a **query parameter**:
  `.../api/v1//news?token=<40-char live key>&category=general&minId=0`. A timeout, a 502 and
  a DNS failure each produced one copy. 26 Finnhub failures were logged over two days, so the
  key was written out 26 times.
- **Second exposure path, worse than the log:** `_run_source()` stored the same unsanitised
  string in `_SOURCES[...]['last_error']`, and `/api/news-scanner/status` **serves that field
  over HTTP**. Any caller of the status endpoint would have been handed the live key.
- **Fix:** `_redact()` strips `token=` / `api_key=` / `apikey=` values, applied at the single
  choke point every message passes through (`_log()`) *and* at the point `last_error` is
  built, so a future call site cannot reintroduce the leak by forgetting to sanitise.
  Verified against the four real captured message shapes plus two synthetic ones.
- **Note:** the log holding the pre-fix copies was a scratch file outside the repo and was
  deleted. The key itself is in `.env`, which is gitignored, and was never committed.

### Watchlist filter applied after the SQL LIMIT — CLOSED (FIXED 2026-08-04)
- **Symptom:** `GET /api/news-scanner/feed?mode=watchlist&limit=5` returned 0 items while the
  identical query at `limit=50` returned 1. Silent wrong answer, not an error.
- **Cause:** the handler selected the newest N rows and *then* filtered them down to the
  watchlist in Python. Any watchlist match ranked below position N was discarded before the
  filter ever saw it — so the smaller the limit, the emptier the watchlist view.
- **Fix:** the filter moved into the SQL `WHERE` clause (`UPPER(IFNULL(ticker,'')) IN (...)`),
  so `LIMIT` applies to already-filtered rows. An empty watchlist short-circuits before the
  query, since `IN ()` is not valid SQL.
- **Verified:** `limit=5` and `limit=50` now both return the same match.

### Two pollers started, doubling the external call rate — CLOSED (FIXED 2026-08-04)
- **Symptom:** the priming fetch logged twice on boot. Two poller threads meant double the
  request rate against **SEC's per-identity budget** and Finnhub's 60/min free tier — i.e. the
  rate-limit discipline the intervals were chosen for was being silently violated at source.
- **Cause:** `start_poller()` was called at module import time, and under `--reload` on Windows
  the app module is imported in more than one process.
- **Fix:** the poller now starts from a FastAPI `lifespan` handler, which runs **only in the
  process that actually serves requests**. `on_event("startup")` was rejected — FastAPI 0.138
  raises a `DeprecationWarning` for it, confirmed by running with `-W error::DeprecationWarning`.
- **Verified:** `grep -c "poller started"` on a clean boot returns exactly 1.

### `uvicorn --reload` detects changes but never completes the restart — OPEN, operational
- **Not caused by this feature; confirmed during it.** `StatReload` logs
  `detected changes in '...'. Reloading...` and then **no `Started server process` line ever
  follows**. The old worker keeps serving, so edited code silently does not take effect.
- **Observed twice**, on `api/server.py` and on `api/news_scanner.py`. Both times the fix that
  "did not work" was in fact never loaded.
- `watchfiles` is **not installed**, so uvicorn falls back to `StatReload`; that is the likely
  contributing factor but was not proven.
- **This is the same trap as the 2026-08-01 stale-listener lesson, in a new form:** there, three
  listeners served pre-fix code; here, one listener serves pre-fix code after a reload that
  looked successful in the log. `netstat` shows exactly one listener in this case, so the
  single-listener check does **not** catch it.
- **Practical rule until fixed: do not trust `--reload`. Kill the process tree and restart, then
  confirm the boot line, before believing any test result.** Every verification in the Stage 1
  build was done after an explicit full restart for this reason.

---

## 2026-08-06 — the acceleration check tested 2 jumps, not the spec's 3

### `_c33_status` used 3 YoY rates / 2 jumps instead of 4 rates / 3 jumps — CLOSED (FIXED 2026-08-06)

- **Severity: signal correctness.** This is the criterion the entire screener exists to
  apply, and it was one transition short of its own definition on every ticker.
- **Symptom, and how it surfaced.** DELL scored GREEN. Its true four most recent Revenue
  YoY rates are `+19.62 → +10.74 → +40.13 → +87.49` (verified independently twice, via
  external data and TradingView screenshots, agreeing to the decimal). The first
  transition is a **deceleration**. The engine's own displayed 3-quarter summary was
  `10.8 → 39.5 → 87.5` — exactly the last three, which alone do show two increases. The
  transition *into* that window was never checked.
- **Cause.** `_c33_status`'s `_last3()` helper took `clean[-3:]` from `rev_yoy` and `npm`
  and built two deltas per metric. `CODE33_SPEC.md` §2.1-2.2 requires 8 raw quarters →
  **4 YoY rates → 3 acceleration jumps**, and explicitly names the shorter form as
  disqualifying: *"With only 6 raw quarters you get 3 YoY rates = only 2 acceleration
  jumps = NOT enough for Code 33."* The implementation was running precisely the
  configuration the spec rejects. It was ported verbatim from the pre-swap
  `utils/code33_engine.py`, and its docstring described the wrong behaviour accurately
  ("3 consecutive quarters"), so nothing ever read as inconsistent.
- **A second, separate defect fixed in the same edit.** Green additionally required
  `d2 >= d1` — that the jump *sizes* grow, a second-derivative test. Confirmed against
  Minervini's source material (via NotebookLM, 2026-08-06) that acceleration means only
  each rate exceeding the prior one. Removed. This one made the filter *too strict*,
  the opposite direction from the window bug, which is why the two partly masked each
  other in the pass counts.
- **Not DELL-specific.** Same shape independently found on **IESC** (margin leg,
  `11.34 → 10.50`) and **RNG** (revenue leg, `4.91 → 4.80`) during manual verification,
  and on **ROST** (margin, `9.19 → 9.14`) and **OOMA** (revenue, `4.05 → 3.49`) during
  this fix's verification.
- **The missing data was already in hand — no new fetch.** The adapter pulls
  `n_quarters + 4` quarters and emits a YoY for all 8 displayed ones, so `rev_yoy` and
  `npm` each carried **8** clean values while the check consumed 3. Confirmed live on
  DELL: `rev_yoy = [9.12, 9.51, 7.23, 5.1, 18.98, 10.83, 39.48, 87.54]`, with the
  unexamined 4th rate `18.98` sitting immediately before the window. Same class of fix as
  the GE restatement one — read what is already there.
- **Fix, in `utils/code33_adapter.py` only. `code33/` untouched** (`git status
  --porcelain -- code33/` empty). `_last3` → `_window` taking `clean[-4:]`, deltas built
  across the whole window. GREEN = full 4-rate window on both metrics with all 3
  transitions strictly positive. RED = any revenue rate negative, or any negative
  transition on either metric.
- **Two judgment calls, both deliberate and commented in-code:**
  1. **The scoreability floor stayed at 3** (`_MIN_RATES = 3`, not raised to
     `_ACCEL_RATES`). Raising it would reclassify short-history tickers red →
     insufficient — a change to the *failure taxonomy*, not the acceleration check — and
     would invalidate `_diagnose_insufficient`'s hardcoded "of 3" wording. A 3-rate
     ticker still cannot reach green, since 3 jumps need 4 rates, so the spec's bar is
     enforced without altering how anything is excluded.
  2. **The negative-RATE gate stayed revenue-only**, exactly as before. Applying it to
     margin would flip every negative-margin company (GKOS, XMTR, URGN, CDNA) to RED for
     a reason unrelated to acceleration; a margin going `-6.4 → -4.5 → -2.6` *is*
     expansion, which is the thing being measured. Negative *transitions* are checked on
     both metrics.
- **Consequence worth knowing: YELLOW is now effectively empty.** Its old meaning was
  "deltas positive but jump sizes shrinking" — i.e. it *was* the second-derivative test.
  With that removed, yellow can only survive an exactly-flat transition (`delta == 0.0`),
  which 2-decimal rounding makes near-impossible. **0 yellow across all 606 tickers.** The
  three-colour badge is now effectively two-tier, and `_scan_state['passed']` (which
  counts green + yellow) is now just the green count. Reconciling the tier vocabulary with
  the spec's ACTIVE/BROKEN/NOT ACTIVE was deliberately left out of scope.
- **Verification.**
  - Baseline captured **before** any edit: all 33 GREEN/YELLOW tickers from the 2026-08-04
    scan plus **37 controls** (24 red, 10 insufficient, 3 excluded_bank).
  - **Byte-level whole-payload comparison, 70 tickers / 1,960 keys: zero violations.**
    All 37 controls byte-identical on every field. 29 status changes, all on the
    pass-list, none on a control.
  - The new logic was *also* replayed offline against the frozen baseline arrays,
    producing the identical 29 changes — which separates the logic change from live-data
    drift. There was none.
  - Structural reason the 10 insufficient controls cannot move: all have `nrev=0` and
    return from `_empty_result` before `_c33_status` is called at all.
  - Exactly one listener on :8000 confirmed before testing (PID 22308, single process
    chain). Fixed code confirmed live over HTTP (DELL `red`, YOU `green`). Logs clean, no
    reload fired mid-scan.
  - **Fresh full 606-ticker scan** (the 2026-08-04 checkpoint was archived first — see the
    checkpoint trap below): completed 606/606, breaker not tripped, no errors.
- **Full-scan result, before → after:**

  | status | before | after |
  |---|---|---|
  | green | 8 | **6** |
  | yellow | 25 | **0** |
  | red | 391 | **418** |
  | insufficient | 82 | **82** |
  | excluded_bank | 100 | **100** |

  31 status changes: 21 yellow→red, 6 green→red, 4 yellow→green. `insufficient` and
  `excluded_bank` counts are **identical**, which is independent corroboration that
  nothing outside the acceleration check moved. Surviving greens: **YOU, AVT, DDOG, XMTR,
  URGN, LQDA** — exactly the six the 70-ticker sample predicted.
- **Two tickers were already stale before any code changed.** NOVT and IRM scored `red` on
  live data while the 2026-08-04 checkpoint still called them yellow/green — a newer
  quarter had landed. Unrelated to this fix; noted because it is why the checkpoint could
  not be used as a baseline directly.

### Checkpoint resume silently reuses pre-fix rows across a code change — OPEN, operational
- **Not a defect in the scan code; a trap for anyone verifying an engine change with it.**
  `_start_scan_job` derives `job_id = sha1(','.join(sorted(set(tickers))))[:12]`, and
  `_scan_worker` skips every ticker already present in that job's checkpoint CSV.
- **So re-running the same ticker list after an engine change resumes the old file and
  skips all 606 tickers**, returning `done` almost immediately with results computed
  entirely by the *old* code — and it looks like a successful fresh scan. Job identity is
  a function of the ticker list only; it has no notion of engine version or
  `CACHE_VERSION`.
- **Worked around here** by moving `scan_f6d3892accf3.csv` to
  `ARCHIVED_prefix_scan_f6d3892accf3.csv.bak` before starting, then confirming
  `resumed_from: 0` in the POST response. That confirmation is the check to run.
- **Possible real fix (not implemented):** fold `CACHE_VERSION` into the `job_id` hash, so
  an engine bump naturally starts a new job instead of silently resuming a stale one.

### SN's failure bucket changed during this work — NOT caused by the fix
- Between the archived scan and the fresh one, SN moved from
  `no reported revenue (pre-revenue company)` to `insufficient revenue history`. It was
  the only `reason`-field change in 606 tickers, and SN was not in the 70-ticker control
  sample, so the byte comparison did not cover it. Investigated rather than assumed.
- **Proven code-independent:** SN was run through the current adapter and again with the
  old `_c33_status` monkeypatched back in — *identical* status and reason under both
  (`only 2 usable revenue quarters`).
- **Actual cause is upstream data.** SN's revenue series now returns only 3 quarters
  (2026-06-30 and 2026-03-31 present via edgartools, 2025-12-31 `None`), so it exits at
  the `len(rev_points) < 5` guard and **never reaches `_c33_status`**. With 1 blank of 3,
  `_is_pre_revenue` is now False where it was previously True, which is what moved the
  bucket.
- **Left open as a separate observation:** a ticker dropping to a 3-quarter pull is worth
  its own look. Not investigated here — out of scope for this fix.

---

## 2026-08-06 — LQDA's 4-digit revenue YoY and the CODE33_SPEC.md §5 N/A guard

### LQDA's extreme YoY rates reach the acceleration check unguarded — INVESTIGATED, NOT A DEFECT

**Outcome: no code was written. A fix was scoped, reconciled, and then deliberately
abandoned on evidence. LQDA's GREEN is correct and intentional.** The `git status` at
close-out was empty — `utils/code33_adapter.py`, `code33/` and `CODE33_SPEC.md` all
untouched.

- **How it surfaced.** During the audit of the six GREEN tickers that followed the
  4-rate/3-jump acceleration fix, LQDA (Liquidia) was found carrying revenue YoY rates of
  `1121.72%`, `3054.65%` and `4158.49%` inside its 4-rate window, on revenue that went
  `$3,120,000 → $132,865,000` across five quarters. `CODE33_SPEC.md` §5 states
  *"abs(YoY%) > 999% → rate = None, quarter stays"*, and a grep of `code33/*.py` plus the
  adapter confirmed **no such guard exists anywhere** — the only plausibility logic
  (`_is_implausible_revenue` / `_is_implausible_net_income`) tests derived-Q4 *raw values*
  against 4x sibling magnitude, never a YoY rate. So the spec requirement was genuinely
  unimplemented. The initial read was that this was a defect of the same species as the
  acceleration-window bug: spec says one thing, code does another.

#### Part 1 — the CRSP/LQDA reconciliation (done first, and it holds)

The obvious risk was re-committing the mistake the "Margin plausibility guard lost in the
engine swap" entry above already closed: CRSP's `-24450.29%` margin is **real, filed,
dollar-exact data**, and that entry concluded a bare magnitude threshold would have
suppressed 7 of its 8 quarters. Before writing anything, the two cases were reconciled:

- **§5 is scoped to YoY RATES, not to extreme percentages generally.** Its header names
  the object outright — *"These guards mark a **YoY% rate** as None"* — and all three of
  its rows are conditions on a two-period comparison (near-zero **prior** value; a
  **prior→current** sign flip; the YoY magnitude itself).
- **Net Profit Margin is not a YoY rate in this engine.** §1 defines it as
  `Net Income / Revenue` — a **level**, computed inside a single quarter. `_c33_status`
  consumes `npm` as levels; there is no NPM-YoY anywhere in the codebase.
- **Therefore CRSP is structurally outside §5.** Its extreme value is a margin level on
  the `npm` array; §5 governs `rev_yoy`. Different array, different computation, different
  consumer. Implementing §5 could not have touched it, and the earlier decision would not
  have been reversed. This was going to be proven empirically by holding CRSP in the
  control set as byte-identical, not argued.
- **The honest limit of that distinction, recorded rather than glossed:** the CRSP entry's
  actual objection — *"a bare magnitude threshold cannot separate"* genuinely-extreme from
  buggy-extreme — **transfers to LQDA**. LQDA's `4158.49%` is arithmetically correct and
  dollar-real. Nulling it would not have corrected an error; it would have declared a true
  number unfit for screening. The defensible difference was never "CRSP real, LQDA broken"
  (both are real) but that a YoY divides by a *different quarter's* value, so a vanishing
  base makes successive rates measure base-smallness rather than growth — plus the fact
  that §5 mandates the rule in writing where the margin tripwire was ad-hoc.

**That reconciliation still stands and is not what stopped the fix.**

#### Part 2 — the Minervini source-material check, which reversed the decision

Before implementing, Minervini's own material was checked (via NotebookLM) on how he
treats explosive percentage growth off a small base. **His methodology does not support
discarding these numbers — it actively seeks them.**

- His **"Size Matters"** material explicitly prioritises small, young companies *because*
  they produce exactly this kind of outsized percentage growth. The magnitude is the
  sought-after signal, not noise to be filtered.
- For genuine turnarounds he wants **bigger** percentage jumps — 100%+ — as evidence of
  real strength. A ceiling is the opposite of his stated preference.
- His actual concern about extreme comparisons is **narrower and different in kind**: a
  company that *artificially depresses a prior quarter* — via manipulated guidance or
  accounting — specifically so the next comparison looks dramatic. That is a
  **fraud/manipulation** concern about how the base was produced, not a concern about how
  large the resulting ratio is. **No magnitude threshold can detect it**, and a magnitude
  threshold would mostly catch the honest cases while missing the dishonest ones.
- **LQDA is a real product launch, not a depressed-base comparison.** Its revenue ramp is
  the genuine article, and it is precisely the company profile the framework exists to
  surface.

**Conclusion: implementing §5's ±999% guard would have worked against the tool's purpose**
— it would have removed the single strongest real accelerator in the universe on the
grounds that its growth was too large.

#### Consequences recorded

- **LQDA's GREEN status is correct and intentional.** No change made, none needed. Its
  4-rate window (`141.51 → 1121.72 → 3054.65 → 4158.49` revenue;
  `-470.51 → -6.50 → 15.82 → 39.79` margin) shows all six transitions positive, and both
  legs are clean five rates deep. It scores GREEN on real, filed data.
- **`CODE33_SPEC.md` §5's ±999% threshold is now FLAGGED as likely NOT reflecting actual
  Minervini methodology.** It reads as a generic statistical convention rather than
  something derived from his source material — note that §5's sibling row
  (`abs(prior EPS) < 0.03`) is an EPS-specific numerical convention too, and EPS has been
  out of this engine's scope since the swap. **Recommendation: reconsider or remove the
  ±999% row from the spec itself in a future pass.** The spec document was deliberately
  **not** edited as part of this close-out — this is a flag, not a spec change, because
  amending the ground-truth document is its own decision.
- **A second, unrelated design question was surfaced and is NOT resolved**, since the guard
  that would have triggered it is not being built. Had any rate been nulled, `_c33_status`
  would have compacted the `None` away (`clean = [x for x in arr if x is not None]`),
  letting the 4-rate window **reach back across the nulled quarter and compare
  non-adjacent quarters**. §2.3 (*"Never skip a quarter … Skipping quarters … produces
  INSUFFICIENT"*) and §1's consecutive `Q0 > Q-1 > Q-2 > Q-3` both argue a `None` inside
  the newest four slots should make the window unevaluable instead. **This affects any
  ticker that already carries a `None` in its newest four positions from a missing
  year-ago quarter — independent of §5.** Left open; it was never sized, because the scope
  scan was stopped when the guard was abandoned.
- **Scope scan discarded.** A full-universe pass measuring the guard's blast radius was
  running when the Minervini finding landed; it was killed unfinished and its partial
  output discarded. No conclusions were drawn from it.

---

## 2026-08-06 — insurance-sector revenue tag selection (OSCR / SLDE / SPB)

### REVENUE_TAGS falls through to an ancillary tag for insurers — INVESTIGATED, NOT A DEFECT

**Outcome: no code was written. Two successive fix designs were scoped and both
abandoned on evidence — the second because measurement showed the defect does not
exist anywhere in the universe. `git status` confirmed clean throughout; `code33/`
and `utils/code33_adapter.py` untouched.**

#### How this surfaced

A long-paused suspicion held that OSCR (Oscar Health) might have an LMND-style
revenue-tag mismatch — reading a narrow sub-component such as premiums-only and
dropping investment income. **It does not.**

- **Bank exclusion correctly does NOT apply.** `bank_signal_tags('OSCR')` returns `[]`;
  Oscar files none of `InterestIncomeExpenseAfterProvisionForLoanLoss`,
  `NoninterestIncome`, `RevenuesNetOfInterestExpense`. The tag list's own docstring
  already predicted this ("REITs, insurers, and asset managers file none of these") and
  OSCR confirms it empirically.
- **The engine reads `Revenues` — priority #1, the true total — on every quarter.**
  Verified against raw `data.sec.gov` companyfacts (CIK 1568651), bypassing both
  secfsdstools and edgartools:

  ```
  2026-03-31: 4,580,862 + 60,614 + 5,718 = 4,647,194  OK
  2025-09-30: 2,923,968 + 53,215 + 8,801 = 2,985,984  OK
  2025-06-30: 2,803,444 + 54,004 + 6,497 = 2,863,945  OK
  2025-03-31: 2,995,821 + 46,112 + 4,330 = 3,046,263  OK
              PremiumsEarnedNet + NetInvestmentIncome + RevFromContract = Revenues
  ```

  Dollar-exact on all four quarters. Investment income **is** included. OSCR's revenue is
  accurate and needs no change.

What that verification *did* raise was a theoretical concern about other insurers.
`REVENUE_TAGS` priority runs `Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax`
→ … . On OSCR, that second tag holds **$5.7M against $4.65B of real revenue — a 0.12%
sliver**. OSCR is safe only because it files `Revenues`, so priority 1 wins. The concern:
an insurer filing the ancillary tag but *not* `Revenues` would have its entire top line
replaced by that sliver, silently and with no error.

#### The full-universe sweep, and why its "AT RISK" call was wrong

All 606 universe tickers were swept against `data.sec.gov` companyfacts. **23 insurers**
were detected (by presence of premium concepts); 22 resolved to `Revenues`. **SLDE**
(Slide Insurance) was the lone outlier, with `RevenueFromContractWithCustomerExcludingAssessedTax`
as its only available revenue tag. It was initially called a live time-bomb — currently
harmless only because SLDE is a June-2025 IPO sitting in `insufficient`, but wrong the
moment it accumulated history.

**That call was wrong, and the method that produced it was flawed in both directions:**

- **The sweep measured concept PRESENCE — does `Revenues` appear anywhere in the filer's
  concept list — not which tag the engine actually RESOLVES per quarter with usable
  values.** These are not the same question.
- **False negative it produced: SPB (Spectrum Brands).** The sweep called SPB safe because
  `Revenues` exists among its concepts. That concept carries no usable *quarterly* values,
  so the engine actually resolves SPB through the same
  `RevenueFromContractWithCustomerExcludingAssessedTax` fallback as SLDE — and SPB is
  live-scored `red` on it today. The sweep never saw this.
- **False positive in the proposed detector.** The scoped fix was "when a company files
  premium concepts, require `Revenues` and refuse to fall through." But the premium-concept
  signal fires on **conglomerates with incidental insurance subsidiaries** — SPB, DE
  (Deere), CVS, C (Citigroup) — not just genuine insurers. Implemented as scoped, it would
  have forced SPB to `Revenues`-only, found nothing usable, and moved it from correctly
  scored `red` to `insufficient`. **The fix would have caused a regression on a
  currently-correct ticker.** Same failure shape the CRSP entry warns about: a signal that
  looks like it identifies the problem but keys on something broader.

#### The decisive test that replaced both flawed approaches

Comparing the revenue the engine actually resolves against `PremiumsEarnedNet` for the
**same quarter** — an inputs-based test, exactly what the CRSP entry asks for instead of
thresholding an output:

| ticker | engine tag | engine revenue | PremiumsEarnedNet | ratio |
|---|---|---|---|---|
| OSCR | Revenues | 4,647,194,000 | 4,580,862,000 | **1.014** |
| **SLDE** | **RevenueFromContractWithCustomer…** | **386,817,000** | **360,635,000** | **1.073** |
| KINS | Revenues | 59,775,736 | 55,868,814 | 1.070 |
| SAFT | Revenues | 314,666,000 | 290,986,000 | 1.081 |
| UFCS | Revenues | 383,726,000 | 354,127,000 | 1.084 |
| SKWD | Revenues | 475,867,000 | 434,007,000 | 1.096 |
| MCY | Revenues | 1,681,765,000 | 1,497,767,000 | 1.123 |
| TRV | Revenues | 12,153,000,000 | 10,753,000,000 | **1.130** |
| UVE | Revenues | 427,033,000 | 377,273,000 | 1.132 |
| GL | Revenues | 1,599,730,000 | 1,297,622,000 | 1.233 |
| AIZ | Revenues | 3,454,200,000 | 2,767,400,000 | **1.248** |
| HG | Revenues | 758,908,000 | 570,515,000 | 1.330 |
| CNO | Revenues | 1,285,200,000 | 680,700,000 | 1.888 |
| VOYA | Revenues | 1,896,000,000 | 716,000,000 | 2.648 |
| **CVS** | Revenues | 106,096,000,000 | 35,117,000,000 | **3.021** |
| PFG | Revenues | 3,529,100,000 | 1,148,100,000 | 3.074 |
| JXN | Revenues | 168,000,000 | 38,000,000 | 4.421 |
| **UHAL** | Revenues | 1,682,027,000 | 18,066,000 | **93.105** |

Two clean clusters, and **both are correct**:

- **Genuine insurers sit at ~1.0-1.3** — revenue is premiums plus investment income and
  fees, so it lands just above premiums.
- **Conglomerates with incidental insurance sit at 2.6-93+** — premiums are immaterial to
  the real business.
- **Not one ticker sits far BELOW 1.0**, which is the only shape the sliver failure mode
  could take. The hypothesised bug does not occur anywhere in the universe.

#### Conclusion

**SLDE's ancillary tag is its genuine, correct total revenue.** At ratio 1.073 it holds
exactly the same economic role as OSCR's `Revenues` at 1.014 — premiums plus investment
income — just filed under a different concept name. Oscar splits its top line across three
concepts and files a proper `Revenues` total, which is why *its* contract-revenue line is a
genuine $5.7M leftover; Slide reports its whole top line under that one tag. Same tag,
completely different role, and reading tag identity without checking the value's magnitude
is what produced the wrong call.

**All 23 insurers in the universe resolve to a correct total revenue. SPB, DE, CVS, C and
the other conglomerates are correct too. No fix warranted, and none was made.** The
`REVENUE_TAGS` fallback is doing precisely the job it exists for — different filers report
the same economic total under different concepts.

#### Process lesson for future audits

**Measuring concept presence is not equivalent to measuring resolved value.** The
presence-based sweep produced a false positive (SLDE) *and* a false negative (SPB) in the
same pass. Any future tag-selection audit must check **the actual per-quarter resolved tag
and the magnitude of its value**, not merely which concepts appear in a filer's history —
and must compare that value against an independent measure of the company's real scale
before concluding anything is wrong.

---

## 2026-08-06 — "no filings of any kind under this CIK" was a false statement

### The local-dataset miss reported itself as "never filed" and blamed a reorg — CLOSED (FIXED 2026-08-06)

- **Diagnostic accuracy only. No status changed, no scored value changed.**
- **What it said vs what was true.** `quarterly_engine.get_quarterly_series` reported
  `no 10-Q/10-K filings found - no filings of any kind under this CIK - if a corporate
  reorganization recently moved this ticker to a new CIK, the operating history is on the
  predecessor (see PREDECESSOR_CIK in ticker_lookup.py)`. **PBT (Permian Basin Royalty
  Trust) has 118 real 10-Q/10-K filings at SEC going back to 1995.** The claim was simply
  false, and the reorg hint sent a reader hunting a corporate action that never happened.
- **Root cause.** `CompanyIndexReader` reads the **local secfsdstools parquet mirror**, so
  an empty result means "absent from the local dataset", not "never filed". The message
  asserted the latter.
- **Why these tickers are genuinely absent, confirmed directly against SEC.** The bulk
  dataset is built from XBRL *financial statements*; a filer publishing none can never
  appear in it. PBT returns **HTTP 404 on companyfacts** — royalty trusts commonly file
  10-Qs carrying no XBRL financial data. BSTZ / RMT / HQH / HQL are **closed-end funds**
  filing N-CSR / NPORT-P / N-Q, with zero 10-Q/10-K and also 404 on companyfacts.
  **All 5 verdicts (`insufficient`) were already correct** — only the explanation was wrong.
- **Fix, in `code33/` (3 files).** Placement is forced by which layer knows what:
  - `quarterly_engine.py` reports only what it actually checked — the local dataset — and
    no longer asserts a reorg. It works from a **CIK and never sees the ticker**, so it
    cannot ask SEC anything.
  - `edgar_fill.py` gains `has_xbrl_quarterly_facts(ticker)`, mirroring the existing
    `bank_signal_tags()` exactly — same `_load_facts_df` source, same per-process cache.
    Since the adapter already calls `bank_signal_tags()` first for every ticker it scores,
    **this costs no extra network call on the normal path.**
  - `pipeline.py` (`_explain_local_dataset_miss`, called from `_fill_gaps`'s existing
    early-return) appends the SEC-side half, because it is the only layer holding the
    ticker. Placed in `_fill_gaps` so the revenue and net-income legs stay symmetric.
  - The two halves are joined by a shared `_LOCAL_MISS_HINT` constant rather than a
    hand-copied substring, so the matcher cannot drift from the emitted text.
  - **The `"no 10-Q/10-K filings found - "` prefix is preserved byte-identically** —
    `api/server.py::_classify_failure` buckets on that substring (server.py:433) and it is
    the only consumer; a repo-wide grep confirmed nothing else matches the old wording.
- **The message now reads**, for PBT and the four funds:
  `no 10-Q/10-K filings found - no filings for this CIK in the local dataset - the bulk
  dataset is built from XBRL financial statements, so a filer publishing none can never
  appear in it - SEC has no XBRL quarterly facts for this ticker either, so there is
  nothing to recover: not a missing-data bug`
  A ticker that *does* have XBRL at SEC gets the opposite clause, which is the only case
  where a predecessor-CIK hunt is worth starting — i.e. the XOM/NVRI signal is retained,
  just no longer misapplied to filers it never fitted.
- **Verification.** Baseline captured before any edit across **31 tickers**: the 5
  affected, NBN, and **25 controls** deliberately including 5 20-F filers (ECO, JOYY, IFS,
  MAAS, OPRA) that hit the *other* branch of the same `if/else`, plus greens, restated
  (AES), predecessor-CIK (XOM, NVRI), extreme-margin (CRSP), non-calendar-FY (DELL) and
  3 excluded banks.
  - **Byte-level whole-payload comparison: 930 keys, ZERO violations.** All 25 controls
    byte-identical on every field including `series_flag` and `excluded_reason`. Every
    status unchanged. The only movement is message text on the 5 affected tickers
    (`excluded_reason`, `series_flag`, and `sources` — which carries the same string via
    `_empty_result`).
  - **`_classify_failure` bucketing verified unchanged on all 31** — the 5 still bucket as
    `no 10-Q/10-K filings in dataset`, NBN still as `ticker/CIK resolution failed`.
  - Server process tree killed before editing (the documented `--reload` hazard), restarted
    after, **exactly one listener confirmed** (PID 23024), HTTP smoke passed
    (PBT `insufficient`, AAPL `red`, YOU `green`).
  - **No fresh full scan run, deliberately:** zero statuses changed, zero scored values
    changed, and every failure bucket is identical, so a 606-ticker scan could not surface
    anything the 31-ticker byte comparison did not already prove. This is the one fix today
    where that judgment applies — the acceleration-window change moved statuses and did get
    a full scan.

### NBN is a dead ticker — NOT an engine defect, no code changed
- `NBN` has **no entry in SEC's `company_tickers.json`**, and no company titled "Northeast
  Bank" resolves. Confirmed against the live SEC ticker map.
- **Current behaviour is already correct and graceful**: `resolve_ticker_to_cik` returns
  `None`, the series carries `NBN: could not resolve to a CIK`, status is `insufficient`,
  and `_classify_failure` buckets it as `ticker/CIK resolution failed`. No exception, no
  crash, no silent wrong number. Verified before and after the message fix — byte-identical.
- **Universe-list maintenance, not an engine problem.** Recorded here so it is not
  re-investigated: the ticker should be dropped from the scan list whenever that list is
  next curated. No matching code was changed.

---

## 2026-08-07 — the revenue sign gate rejected Minervini's own worked example

### `_c33_status` instant-rejected any window containing a negative revenue rate — CLOSED (FIXED 2026-08-07)

- **Severity: signal correctness.** A hard gate ran *before* the acceleration test and
  threw out the exact setup shape the methodology is built to find.
- **The gate.** `utils/code33_adapter.py`: `if any(r < 0 for r in rev_w): return 'red'`.
  One negative rate anywhere in the 4-rate window was an instant reject.
- **What proves it wrong — the source material, not a judgment call.** Minervini's own
  worked Code 33 example (*Trade Like a Stock Market Wizard*, ch. 8, "The Code 33") has a
  qualifying revenue sequence of **-22% → +3% → +16% → +38%**, and his EPS example starts
  at **-34%**. Both start negative. The old gate rejected them on the first element and
  never reached the acceleration test. This is a **sign** question settled by a cited
  example — deliberately NOT the same class as the DELL window-length fix (structural, spec
  §2.1) or the LQDA magnitude question (statistical, and correctly abandoned). It should
  not be conflated with either.
- **The gate was never a data guard.** Traced through git: it entered in `b565b72`
  (2026-06-23) with the comment *"EPS and Rev rates must all be positive (negative =
  pre-profit / declining)"*, citing a "CLAUDE.md §8" rule that no longer exists; carried
  verbatim through the `dc77f59` engine swap; preserved deliberately (and wrongly) by
  today's `edc3b8f` acceleration fix. Three independent absences confirm there was no
  data-integrity reason: **no `bug_report.md` entry** ever justified it; it never guarded a
  named bad-data pattern (the TRT `_to_m()` and ±1000% margin work is separate machinery on
  different quantities); and **`CODE33_SPEC.md` never required it** — §1's condition is the
  pure ordering `Q0 > Q-1 > Q-2 > Q-3`, and §5 explicitly **computes and keeps** sign-flipped
  rates, labelling them `[NM]` rather than rejecting them.
- **The asymmetry it created.** Margin already had no sign gate at all and correctly
  accepts `-6.42 → -4.49 → -2.57 → -2.32` (XMTR scores GREEN on exactly that). Revenue was
  held to a stricter standard for no documented reason.

#### The rule as implemented — a refinement, not a blanket removal

A second round of source-material confirmation established that **blanket removal would
over-correct**. The book does not explicitly ban a still-negative-throughout sequence, but
the methodology points hard against it: it requires real revenue **growth**, not merely
less shrinkage, demands *rapid* growth, and for turnarounds explicitly wants current
results strongly positive (+100% or better), not just improving. His own example **ends at
+38%**. A sequence like `-50 → -40 → -30 → -20` accelerates on every step while revenue is
still falling year-over-year in every quarter of the window — improvement, not growth.

So the test is the **endpoint**, not the whole window:

```python
- if any(r < 0 for r in rev_w):    # rejects Minervini's own example
+ if rev_w[-1] < 0:                # only the NEWEST rate must be positive
      return 'red', None, None
```

Revenue-only. **Margin keeps no sign gate**, unchanged. The transition test (each rate
higher than the last, 3 consecutive times across 4 rates) is untouched — this changes only
the sign gate.

- **Placement: `utils/code33_adapter.py` only, `code33/` untouched.** `_c33_status` is
  badge/methodology logic and lives in the adapter; `code33/` is data extraction. Same
  boundary as the acceleration fix.

#### Scope, measured across the full 606-ticker universe before implementing

```
tickers with >=1 negative rate in window (blanket gate fires):  185
  ...newest rate NEGATIVE  -> still correctly red:               59
  ...newest rate POSITIVE  -> re-evaluated:                     126
     ...of those, still red on their transitions anyway:        121
tickers actually changing:                                        5
tickers where the revised rule differs from blanket REMOVAL:      0
```

The gate was short-circuiting **126** tickers on an earlier quarter's sign. 121 were red on
their transitions anyway, so it was masking a correct answer; **5 were genuinely wrong**.
The **59** with a negative newest rate stay red — the population the refinement protects.
No all-negative-throughout sequence exists in the universe today, so the refinement costs
nothing in current coverage while still guarding the case on principle.

#### The 5 changes, with the sequences that explain each

| ticker | before | after | revenue YoY window (oldest → newest) | margin window |
|---|---|---|---|---|
| CSX | red | **yellow** | −0.88 → −0.88 → +1.72 → +10.10 | +19.35 → +20.52 → +23.18 → +25.46 |
| HELE | red | **green** | −10.84 → −8.95 → −3.37 → +8.20 | −121.27 → −71.48 → −16.39 → +8.89 |
| INSW | red | **green** | −24.00 → −12.79 → +37.65 → +77.47 | +31.51 → +35.92 → +47.60 → +87.92 |
| ST | red | **green** | −5.17 → +1.12 → +2.58 → +5.00 | −17.44 → +6.89 → +9.32 → +10.31 |
| VLO | red | **green** | −2.15 → −1.25 → +7.02 → +48.80 | +3.40 → +3.73 → +3.90 → +8.36 |

Every one starts negative, accelerates on all three transitions, and ends positive — the
Chapter 8 shape exactly. `INSW` (−24% → +77%) is the closest analogue to the book's own
example. `CSX` lands yellow rather than green because of its flat `−0.88 → −0.88`
transition (delta exactly 0), the narrow surviving yellow case.

#### Verification

- **Pass 1 before any edit:** full-universe pull capturing complete payloads for all 606
  tickers plus the scope table above.
- **Byte-level comparison, 57 tickers / 1,596 keys: ZERO violations.** 52 controls
  byte-identical on every field; `status` moved only on the 5 predicted tickers. Controls
  were drawn to hit the exact groups this touches: **12 newest-rate-negative** (all held),
  **13 re-evaluated-but-still-red** (all unchanged), all current greens, 6 insufficient,
  4 excluded banks, plus GE / DELL / NVRI / PBT.
- **Proof the change cannot create a red:** `newest < 0` implies `any < 0`, so the new
  red-set is a strict **subset** of the old. Measured across all 606: **0 tickers turn
  non-red into red.**
- Server tree killed before editing (the documented `--reload` hazard); **exactly one
  listener confirmed** after restart (PID 19956); fixed code verified live over HTTP
  (HELE/ST/INSW/VLO green, CSX yellow, AAPL red).
- **Fresh full 606-ticker scan** (prior checkpoint archived first; `resumed_from: 0`
  confirmed): 606/606, breaker not tripped, no error.

| status | before | after |
|---|---|---|
| green | 6 | **9** |
| yellow | 0 | **1** |
| red | 418 | **415** |
| insufficient | 82 | **81** |
| excluded_bank | 100 | **100** |

- **7 status changes in the scan, of which only 5 are this fix.** `DDOG` (green→red) and
  `GRDN` (insufficient→red) are **pre-existing data drift, proven not caused by the change**:
  both were *already* red in the Pass-1 baseline captured **before** the edit. DDOG's newest
  margin fell `5.22 → 3.97`, a negative transition from a newly-landed quarter; GRDN gained
  enough history to become scoreable and lands red on `20.05 → 2.21`. GRDN's `reason`
  emptying is just normal red-status behaviour. Neither is reachable by a gate that can only
  ever remove a rejection.

---

## 2026-08-07 — bank exclusion fired on non-banks; PLXS revenue read 1000x too small

### The bank tripwire excluded 4 companies that are not lenders — CLOSED (FIXED 2026-08-07)

- **The exclusion's one stated justification never applied to them.** CLAUDE.md records banks
  as refused because *"their revenue is silently wrong under standard XBRL tags, confirmed on
  FULT"*, and explicitly notes this is *"a different category from a sector-fit judgement"*.
  `BANK_SIGNAL_TAGS`' own docstring says *"Deliberately NOT sector labels or ticker lists."*
  So the rule is falsifiable per ticker: if a ticker's revenue is demonstrably correct, the
  justification does not cover it.
- **KMX (CarMax) is the clear case.** It trips one tag,
  `InterestIncomeExpenseAfterProvisionForLoanLoss`, from CarMax Auto Finance — a captive
  lending arm behind a used-car retailer. Its revenue was being read **correctly the whole
  time**: the engine resolves priority-1 `Revenues` and produces $6-8B/quarter, verified
  against SEC (`Revenues` 8,013,519,000 = `RevenueFromContract...` 8,013,500,000, with
  `CostOfRevenue` 89.3% — a thin retail margin). Contrast FULT, the proven true positive,
  where the engine reads **$69.8M** while the interest line alone is **$247.6M** — fee income
  only, net interest income silently dropped. KMX shows nothing of that shape.
- **AN (AutoNation) and PAG (Penske) — same industry, same captive-finance model — file zero
  bank-signal tags.** KMX is unusual in how it *tags*, not in what it *is*.

#### The measurement, and a wrong first attempt recorded deliberately

The first metric tried was "ratio of whichever `BANK_SIGNAL_TAGS` entry fired first to
revenue". **It was unsound and would have released real lenders.** The three signal tags mean
opposite things — `NoninterestIncome` is *by definition the non-lending part* — so:

| ticker | flawed metric | true lending share | what it is |
|---|---|---|---|
| WRLD | 12.9% | **87.3%** | World Acceptance, consumer lender |
| ATLC | 0.1% | **100.0%** | Atlanticus, consumer credit |

A `<25%` rule on the flawed metric would have cleared both. Same error class as the SLDE/SPB
insurer episode: measuring a convenient number instead of the meaningful one.

**The correct metric is lending income (`InterestAndDividendIncomeOperating`,
`InterestAndFeeIncomeLoans*`, `InterestIncomeOperating`, ...) divided by total revenue**,
chosen semantically, never by tag-priority order. Validated across all 100 excluded tickers:

```
KMX      5.8%   <- released
                    (empty band — no ticker anywhere between 5.8% and 68.5%)
HASI    68.5%   <- STAYS EXCLUDED
STT     70.2%   <- lowest genuine lender
MS 74.5%  QCRH 82.2%  WRLD 87.3%  RBCAA 94.5%  PNC 97.4%  USB 98.5%
ATLC 100.0%  COF 106.6%  ... FULT 558.5% ... AVBH 38,651.5%
```

#### The rule as shipped

Threshold **50%** = *"a majority of the business is banking/lending activity"*. Chosen for
what it means, not where it sits — the band 5.8%-68.5% is empty, so any threshold inside it
gives the same answer. **Honest note: 50% is not uniformly safer than 25%** — it is further
from KMX (44.2pp vs 19.2pp) but *closer* to HASI (18.5pp vs 43.5pp). The principle is the
argument, not the margin.

Two branches, both validated over the full excluded set:
1. **Files no lending-income concept at all** -> signal is vestigial -> release. Provably
   safe: 97 of 100 excluded tickers file one, and **every bank-SIC ticker does**. The 3 that
   file none are exactly the false positives.
2. **Files one, but lending income is a minority of revenue** -> not a lender -> release.

**Both branches additionally require a usable revenue series.** Anything unmeasurable stays
excluded — unverifiable must never mean cleared.

- **HASI: deliberately stays excluded, decision settled.** HA Sustainable Infrastructure
  Capital (SIC *Investors, NEC*) is a specialty finance company —
  `InterestIncomeOperating` 66,394,000 / `Revenues` 96,941,000 = **68.5%**, with
  `InterestExpense` 99,275,000 *exceeding* quarterly revenue. A majority of its revenue is
  banking-activity income, so it is correctly treated as a bank **even though its own numbers
  are individually accurate**.
- **Standing guidance for a future borderline case, recorded and deliberately NOT encoded:**
  today's gap is wide and nothing sits near the line. If a future ticker lands close to
  `_BANK_LENDING_SHARE`, do not decide on the ratio alone — read how the company describes
  its own core business in its 10-K and how it positions its product, and use that as the
  tie-breaker. Instruction for a human reviewer, not automated logic.

#### A defect in the first implementation, caught by verification

The shipped code initially **omitted the "AND a usable revenue series exists" condition**, on
the mistaken reasoning that it was self-enforcing downstream. It is not. **NEWT (NewtekOne,
SIC National Commercial Banks) — a genuine bank — was released**: it has no usable revenue
series at all, so `lending_income_share` computed off a mismatched pair in the raw facts,
returned 4.4%, and cleared it. The validation sweep missed this because it selected the
measurement quarter differently from the function that shipped. Fixed by verifying against
the pulled series, the only authoritative answer; NEWT is back to `excluded_bank`.

### PLXS revenue read 1000x too small — CLOSED (FIXED 2026-08-07)

- **Cause is filer-side, at SEC.** Plexus tags
  `RevenueFromContractWithCustomerExcludingAssessedTax` **in thousands** while tagging
  `...IncludingAssessedTax` in dollars for the same period — identical digits, exactly 1000x
  apart, on **6 quarters** (newest 2026-07-04: `1,304,778` vs `1,304,778,000`).
- **Only the edgartools gap-fill path was affected.** `REVENUE_TAGS` orders *Excluding* before
  *Including*, so `fetch_discrete_quarter` picked the mis-scaled value; secfsdstools picked
  *Including* on the same quarters and was correct. Net effect: a 1000x cliff mid-series
  (`...980M, 1.07B, 1.16M, 1.30M`).
- **Fix: a scale guard in `fetch_discrete_quarter`.** A candidate under 1/100th of the
  series' established magnitude is **skipped so tag priority falls through to the next tag**,
  recovering the correctly-scaled figure rather than dropping the quarter.
  `pipeline._fill_gaps` supplies the median of known values as the reference.
  **Self-limiting**: the reference is `None` until a series has established scale, so a
  first-quarter pull can never trip it, and the guard only ever demotes a candidate — it
  never invents a value. Confirmed firing in the log; PLXS now reads **1,304,778,000**.
- **Universe scope, measured — and two wrong counts recorded on the way.** A crude "≥500x
  between any two revenue concepts" test flagged **10** tickers; it conflated *scale errors*
  with *genuinely different quantities*. A second pass comparing only the min/max pair still
  missed two real cases. The correct test is **same mantissa, differing by a power of 1000**:

  | ticker | newest affected | scale |
  |---|---|---|
  | **PLXS** | **2026-07-04** | 1,000x |
  | IRDM | 2018-03-31 | 1,000x |
  | LUV | 2011-09-30 | 1,000,000x |

  7 false alarms confirmed as different quantities — including **OSCR** (813x: the $5.7M
  ancillary line vs $4.65B total, already verified dollar-exact), AER, SKWD, TVTX, ANDE, CTO,
  KWR. **Only PLXS has live impact**; IRDM and LUV are 7-15 years outside any 12-quarter
  window. The bug class is real and recurs, which is why a generic guard is warranted.
- **Hard dependency, honoured:** PLXS needed **both** fixes. Releasing it from bank exclusion
  before fixing the scale bug would have immediately scored it on a 1000x-broken series.

#### Verification (both fixes together)

- Baseline before any edit: full payloads for **all 100 excluded tickers + 51 controls**.
- **Byte-level comparison, 151 tickers / 4,116 keys.** All 96 non-released excluded tickers
  and every control byte-identical. `still excluded_bank = 96`, expected 96.
- **OSCR was the only control diff and is proven to be new-filing drift, not the fix:** every
  overlapping value bit-identical with the window advanced exactly one quarter
  (`before[1:] == after[:-1]` true for rev, rev_yoy, npm, ni and all date/label arrays); its
  10-Q for 2026-06-30 was filed 2026-08-07, the same day. OSCR files no bank tags, and the
  scale guard can only reject candidates — neither fix can add a quarter.
- Server tree killed before editing (documented `--reload` hazard); **one listener confirmed**
  after restart (PID 18640); all four releases plus HASI/NEWT verified live over HTTP.
- **Fresh full 606-ticker scan** (checkpoint archived, `resumed_from: 0`), 606/606, breaker
  not tripped:

| status | before | after |
|---|---|---|
| red | 415 | **419** |
| excluded_bank | 100 | **96** |
| insufficient | 81 | **81** |
| green | 9 | **9** |
| yellow | 1 | **1** |

  **Exactly 4 status changes — KMX, LOVE, PLXS, SKWD, all `excluded_bank` -> `red`.** Nothing
  else moved anywhere in the universe.

---

## 2026-08-07 — the app could not boot from requirements.txt

### `pip install -r requirements.txt` produced an environment the app crashes in — CLOSED (FIXED 2026-08-07)

- **Severity: total. On a genuinely clean install the server never starts.**
  ```
  RuntimeError: Form data requires "python-multipart" to be installed.
  ```
  Raised from `api/server.py:341`, inside the `@app.post("/api/scan")` decorator, while
  FastAPI builds the route **at import time** — so it happens before the socket is ever
  opened, and no endpoint is reachable.
- **Root cause, and it is a direct consequence of `bdf1e71`.** `/api/scan` takes
  `file: UploadFile = File(...)`, which FastAPI cannot construct without `python-multipart`.
  That package was never declared — it was only ever present as a **transitive dependency of
  `streamlit`**:
  ```
  Name: python-multipart   Version: 0.0.32   Required-by: streamlit
  ```
  `bdf1e71` removed `streamlit` after an audit found zero imports. That was **correct on its
  own terms** — streamlit genuinely is not imported anywhere (re-confirmed: zero hits across
  all 18 source files, and zero dynamic imports of any kind — no `importlib`, `__import__`,
  `exec` or `eval` anywhere in the codebase). But removing it silently removed the only thing
  that declared `python-multipart`.
- **Why nobody noticed for six days:** the local `.venv` still has `streamlit` installed —
  removing a line from `requirements.txt` does not uninstall anything — so the app kept
  working locally. **A packaging gap of this shape is invisible from inside the environment
  that has the gap.**

#### A second, independent gap in the same endpoint family

`/api/news`'s two primary sources were also undeclared:
```
[news] SeekingAlpha failed: No module named 'FinNews'
[news] tradingview-scraper failed: No module named 'tradingview_scraper'
```
Both imports sit inside `try/except Exception` blocks that only `print`, so the endpoint
still returned **HTTP 200** — with 10 items, all from the yfinance fallback. Working from the
outside, silently running on one source of three.

#### A third gap, found ONLY by booting — declaring the packages was not enough

Adding `FinNews` and `tradingview-scraper` made them install but **still not import**:
```
[news] SeekingAlpha failed: No module named 'pkg_resources'
```
`FinNews/source_object.py:4` does a bare `import pkg_resources`, and **setuptools deleted
`pkg_resources` in 81.0.0**. A fresh install pulls setuptools 83.x:
```
CLEAN env    setuptools=83.0.0   pkg_resources=False
REAL .venv   setuptools=80.10.2  pkg_resources=True
```
The running `.venv` predates the removal, which is why this too was invisible locally. Fixed
with a **ceiling**, `setuptools<81` — the constraint is "must still ship pkg_resources", so a
ceiling expresses it correctly where a pin would not.

#### The fix

Four lines added to `requirements.txt`, each commented in the existing style, all pinned to
the versions the running environment actually has (checked, not guessed):
```
python-multipart==0.0.32
FinNews==1.1.0
tradingview-scraper==0.4.20
setuptools<81
```
Plus a standing instruction at the top of the file: **boot the app, do not just import.**

#### Verification — in a throwaway venv, never the real one

- Fresh venv built from Python 3.12.8 in the scratchpad. `python-multipart` was
  **deliberately uninstalled first**, so the install had to prove `requirements.txt` itself
  supplies it rather than relying on residue from the earlier probe.
- `pip install -r requirements.txt` completes, exit 0.
- **App boots with no crash; exactly one listener on :8000** (PID 6180), served by the clean
  env with no `.venv` process in the chain.
- End-to-end on the clean env:
  - `/api/ticker/AAPL` -> `red`, $312.51, mcap 4.6T
  - `/api/financials/AAPL` -> 8 real quarters (`2024-12-31 rev=124,300,000,000 rev_yoy=3.95
    npm=29.23`)
  - `/api/scan` multipart upload -> job accepted, 1/1 completed, no error
  - `/api/news/AAPL` -> **30 items, zero source failures logged**, up from 10:
    **15 Seeking Alpha (FinNews)** plus Reuters / TradingView / Dow Jones Newswires /
    GuruFocus / Binance News (tradingview-scraper) alongside the yfinance names.
    All three sources confirmed live, and all three imports proved directly.
- **The real `.venv` and running server were untouched throughout** — re-checked after the
  test: `python-multipart 0.0.32`, `FinNews 1.1.0`, `tradingview-scraper 0.4.20`,
  `setuptools 80.10.2`, `streamlit 1.58.0`, all unchanged. `git status` shows only
  `requirements.txt`.

#### Why the earlier verification missed this

`bdf1e71` was verified by installing into a clean venv and **importing every declared
package**. Every declared package did import — the file's problem was a package it did *not*
declare, and the failure only materialises when FastAPI builds a route. **An import-only
smoke test cannot detect a missing runtime dependency of the framework itself.** The bar is
now written into the file: create a fresh venv, install from it, start the server, hit a real
endpoint. It passed the import test twice while the app could not start.

---

## 2026-08-09 — net margin ran on a different basis than revenue YoY

**Commit:** (this change) — `code33/net_margin.py` only.

### What was wrong

`pair_margin_series()` computed `margin = ni_value / revenue_value` from the
**as-first-filed** figures on both legs, while `utils/code33_adapter.py::_yoy_value()`
had been computing revenue YoY on the filer's own **recast** basis since the GE fix
(2026-08-02, see "corporate actions inside a single CIK" above). So the two legs of the
same Code 33 signal ran on two different bases.

The ratio itself was never internally incoherent — numerator and denominator always came
from the same filing. The defect is one level up, in the **acceleration test**: a
since-corrected quarter sitting next to never-revised neighbours makes a transition that
is partly artifact.

### The fix

New `_restated_basis(point)` in `code33/net_margin.py`, mirroring `_yoy_value()` exactly
and for the same reason. Applied to **both** legs — NI and revenue alike.

**Display values are deliberately untouched.** `MarginPoint.net_income` / `.revenue` still
carry the as-filed record out to the API, with `ni_restated` / `ni_restated_value` /
`revenue_restated` / `revenue_restated_value` alongside to say where a filer revised
itself. The calculation basis is held in separate locals (`revenue_basis` / `ni_basis`)
precisely so reusing the display locals could not silently rewrite the as-filed arrays.

Placement in `net_margin.py` rather than the adapter follows where the computation lives:
the margin is computed in this module, exactly as the YoY is computed in the adapter.

### Scope, measured before implementing (full 606)

25 tickers carry a restated NI in the displayed window, 20 of their margin series actually
move, and **ZERO statuses change**. This is a latent correctness gap being closed, not an
active scoring bug.

### MAGN — the one apparent deviation, and why it is NOT a data error

Two tickers deviated from the original prediction. Both were prediction errors, not code
errors. The second, MAGN, was checked independently against `data.sec.gov` raw XBRL
(bypassing secfsdstools and edgartools entirely) because a ~69% revenue correction is
unusual enough to demand a named cause.

| | period | value | source filing |
|---|---|---|---|
| Original | 2024-04-01 → 2024-06-30 | **$329,443,000** | 10-Q filed 2024-08-08, FY2024 Q2, accn `0000041719-24-000032` |
| Later | 2024-03-31 → 2024-06-29 | **$556,000,000** | 10-Q filed 2025-08-06, FY2025 Q3, accn `0001140361-25-029147` |

Both on `RevenueFromContractWithCustomerIncludingAssessedTax`, `qtrs=1`. The engine's
`rev_restated_value` is **556,000,000 exactly** — dollar-for-dollar against SEC. NI is the
same shape: as-filed −$16,279,000, later +$19,000,000, engine `ni_restated_value` =
19,000,000. Margin = 19,000,000 / 556,000,000 = **3.42%**, which is what the fix produces.
The originally mis-predicted 5.77% was 19M / 329.443M — restated NI over as-filed revenue,
i.e. the mixed basis this fix exists to eliminate.

**There is no 69% restatement. It is a reverse merger.** Magnera's own 10-Q states it:

> "On November 4, 2024 … Treasure Holdco, Inc. ('Treasure'), which was a wholly owned
> subsidiary of Berry Global Group, Inc. … completed its merger with the Glatfelter
> Corporation which concurrently changed its name to Magnera Corporation. As a result,
> pre-Transaction Treasure shareholders received shares of Magnera representing 90% of the
> combined company and GLT shareholders retained 10%. **As Treasure was identified as the
> accounting acquirer, the prior year presentation represents standalone Treasure
> results** with the acquisition method of accounting being applied to the assets acquired
> and liabilities assumed of GLT."

CIK 41719 confirms it: `formerNames` = Glatfelter Corp until 2024-11-04, and
`fiscalYearEnd` changed 12/31 → **09/26** (Berry's 52/53-week calendar), which is why the
later period ends 2024-06-**29** rather than at calendar quarter-end.

So $329M is Glatfelter's Q2 2024 and $556M is Treasure's fiscal Q3 2024 — **two different
reporting entities over near-identical 90-day windows. Neither figure corrects the other.**

The two are paired because `_attach_restatement_flags` matches on exact `ddate`, and
DERA's data sets round period end to the nearest month-end, so 2024-06-29 and 2024-06-30
both become `20240630`. Same tag, same `qtrs=1`, different `adsh`, latest-filed wins.

**Conclusion: the value is accurate and there is no upstream data issue.** What is
imprecise is the vocabulary — `restated` here means "a later filing published a different
figure for this ddate", and in MAGN's case that different figure belongs to a different
company. Worth knowing when reading the flag; not a defect in the number.

### Verified

Full 606-ticker byte comparison passed; MAGN confirmed dollar-exact against SEC as above;
zero unexplained status changes. Single listener confirmed before testing.

---

## 2026-08-09 — restatement detection skipped every derived Q4

**Commit:** (this change) — `code33/quarterly_engine.py` only. Separate from, and stacked on
top of, the net-margin recast-basis fix above.

### What was wrong

`_attach_restatement_flags` gated on `point.source != "reported"`, so a **derived Q4**
(`derived_fy_minus_quarters`, back-solved as FY minus Q1+Q2+Q3) could never be flagged as
restated — even when the filer's own later filing published a different discrete figure
for that exact period.

The stated justification was *"a derived value already combines multiple filings, so
there's no single figure to check for restatement."* **Tested and false.** That describes
the point's OWN provenance, which the query never reads. The query asks whether some
LATER filing published a discrete `qtrs=1` figure for the same `ddate`, and a derived
point carries both fields that needs: `.adsh` (the 10-K it was back-solved from) and
`.tag` (the FY tag).

Found while verifying the margin fix: MAGN's 2024-12-31 revenue YoY read **119.11%**,
comparing Magnera/Treasure's $702M against Glatfelter's derived-Q4 base of $320.382M —
two different accounting entities, not one company growing.

### Scope — measured across all 606 tickers before implementing

**27 tickers, 37 quarters.** Every one triaged against `data.sec.gov` directly.
Distribution: 7 at >=50%, 9 at 10-50%, 13 at 2-10%, 3 at 0.5-2%, 5 under 0.5%.

| ticker | quarter | derived | later-published | delta | cause |
|---|---|---|---|---|---|
| DINO | 2024-12-31 | 6,499,884,000 | 28,580,000,000 | +339.7% | **filer mis-tag — NOT a restatement** |
| DBRG | 2023-12-31 | -330,790,000 | 350,310,000 | +205.9% | derived value already implausible (negative revenue) |
| ATI | 2022-12-31 | 76,900,000 | 193,000,000 | +151.0% | NI recast |
| MAGN | 2023-12-31 | 320,382,000 | 519,000,000 | +62.0% | reverse merger, entity swap |
| CALY | 2024-12-31 | 924,400,000 | 371,400,000 | -59.8% | Topgolf separation |
| ADEA | 2021-12-31 | 214,449,000 | 89,705,000 | -58.2% | Xperi separation |
| DD | 2024-12-31 | 3,092,000,000 | 1,689,000,000 | -45.4% | Qnity electronics spinoff |
| PBI | 2023-12-31 | 871,578,000 | 526,416,000 | -39.6% | GEC exit |
| JNJ | 2022-12-31 | 23,706,000,000 | 19,939,000,000 | -15.9% | Kenvue separation |

**This is not a reverse-merger niche.** The dominant class is the ordinary
continuing-operations recast — exactly what this function was built for on the
3M/Solventum case — and **30 of the 37 later figures come from a 10-K comparative**, not
from a fiscal-calendar change.

### The DINO guard — why it is not optional

HF Sinclair's FY2025 10-K tags **$28,580,000,000 for 2024-10-01..2024-12-31 as `qtrs=1`** —
bit-identical to the `qtrs=4` fact for 2024-01-01..2024-12-31 in the SAME filing. A filer
XBRL error at SEC.

Naively extending the flag replaces DINO's correct derived Q4 ($6.5B, plausible) with an
annual figure and drags **a quarter INSIDE the 4-rate scoring window from -0.55% to
-77.38%**. The fix would have corrupted data it was meant to correct.

`_is_annual_mistagged_as_quarter()` rejects a candidate whose value equals a `qtrs=4` fact
in the same accession at the same ddate and tag. A fiscal year ends on the same date as
its own Q4, so the annual fact shares the quarter's ddate; the test is **exact value
equality within one accession — an INPUT check, deliberately not a size heuristic.** A
magnitude threshold is the mistake the +/-1000% margin guard already taught: it cannot
separate a mis-tag from a real corporate action, and the real restatements here run 0.01%
to 206% in BOTH directions.

Placed **before** the latest-filed sort, not after: a mis-tagged row is not a weaker
observation of the quarter, it is not an observation of that quarter at all, so a genuine
earlier restatement behind it must still be able to win.

Applied to **every** candidate, not just derived ones — a mis-tagged annual figure is not
a valid restatement for a reported point either, and gating it by source would be
arbitrary. That widened the blast radius beyond what the investigation measured, so it was
proven separately (below).

### Two things deliberately NOT done, both evidence-backed

- **Exact-tag matching kept.** Relaxing it to "any tag in the priority list" surfaces 7
  more apparent restatements, and all 7 are cross-CONCEPT comparisons rather than
  revisions: `NetIncomeLoss` vs `ProfitLoss` (NCI-inclusive, the AES case) on BAX/BNY/PAA,
  `NetIncomeLoss` vs `...AvailableToCommonStockholdersBasic` on DBRG, `Revenues` vs
  `RevenueFromContractWithCustomer...` on DLTR (-42.6%) and SON (-18.3%). Load-bearing.
- **No magnitude/precision threshold added.** The 5 sub-0.5% findings (ELAN, UFPT, LGND,
  BY, CSX) all round away at 2dp and produce zero downstream change. A threshold would
  have been unnecessary machinery.

### No adapter change needed

`_yoy_value()` keys purely off `restated`/`restated_value`, and (since the margin fix
above) so does `_restated_basis()`. Both corrections propagate automatically — same shape
as the GE fix. `utils/code33_adapter.py` untouched.

### Verification

**Byte-level whole-payload comparison — 75 tickers, 2,100 keys, zero tolerance.**
27 affected + 48 controls spanning 9 green / 1 yellow / 45 red / 10 insufficient /
10 excluded_bank. Baseline captured AFTER the margin fix was committed, so that fix is the
floor being measured from.

```
tickers compared      : 75
keys compared         : 2100
tickers with any diff : 12
  of which AFFECTED   : 12 / 27
  of which CONTROL    : 0      <- zero violations
byte-identical        : 63
STATUS CHANGES        : 0
```

The 12 movers are the 13 predicted minus DINO. Margin leg moved on 6 (CALY, DD, MCFT,
MIDD, PAA, PAG) — the predicted 7 minus DINO. **Nothing moved that was not predicted.**

**DINO guard proof — byte-identical before/after**, including its three pre-existing
*reported*-point restatement flags (7027/7846/7207M), which the guard left alone. The
in-window 2025-12-31 rate held at -0.55%. Confirmed live over HTTP.

**MAGN corrected 119.11% -> 35.26%**, matching the prediction exactly.

**Containment, universe-wide: 14,955 reported points across all 606 tickers, ZERO
behaviour changes.** Old and new logic computed from identical inputs in one pass and
diffed. The one entry the diff initially reported was a `NaN != NaN` artifact of the check
script itself — both sides identical (see the IDYA note below). Guard rejections
universe-wide: exactly 1, DINO. New derived flags: 36 (the 37 findings minus DINO).

**Status impact today: 0 of 27.** PAG was the ticker to watch — it was the single status
change in the GE restatement fix and its affected quarter is in-window — and it moved
+0.64 -> -3.82 on revenue and 3.06 -> 3.09 on margin without crossing a boundary.

### On "zero status changes" — this is not structural protection

The eight tickers with an affected value INSIDE the 4-rate window (DINO, CALY, DD, MCFT,
MIDD, PAG, PAA, PAGP) move by 2.6 to 59 percentage points:

| ticker | in-window rate before -> after |
|---|---|
| CALY | -60.24 -> -1.05 |
| DD | -45.25 -> +0.24 |
| MCFT | +18.36 -> +46.39 |
| MIDD | -14.54 -> +4.53 |
| PAG | +0.64 -> -3.82 |
| PAA / PAGP | -14.81 -> -12.21 |
| DINO | -0.55 -> -0.55 (guard held) |

`_c33_status` turns red on `any(d < 0 ...)` across window transitions, and a 19-59pp move
flips a transition sign trivially. Nothing changed today because these tickers are red for
other reasons. **That is coincidence, not protection** — the GE fix's own audit moved 36
YoY values and flipped one status. Expect a nonzero rate as quarters land.

MAGN's own artifact is permanently out of the window (`_window()` takes the newest 4
non-null rates and windows only advance), so it was never at risk going forward; it is
corrected for accuracy, not safety.

### Fresh full 606-ticker scan

Checkpoint archived as `ARCHIVED_pre_derivedq4_scan_f6d3892accf3.csv.bak` first;
`resumed_from: 0` confirmed on start, so no pre-fix rows carried across the code change.
606/606 completed, breaker not tripped, no errors.

| status | before | after | delta |
|---|---|---|---|
| green | 9 | 9 | 0 |
| yellow | 1 | 1 | 0 |
| red | 419 | 419 | 0 |
| insufficient | 81 | 81 | 0 |
| excluded_bank | 96 | 96 | 0 |
| **TOTAL** | **606** | **606** | |

**Zero status changes universe-wide.** Every bucket identical.

35 tickers moved a scored VALUE, and they separate cleanly into two populations:

- **6 in-place changes, all in the affected set** — CALY, DD, MIDD, PAA, PAG, PAGP. This
  is the fix. (LGND is in the affected set but its finding sits at 2021-12-31, long outside
  the 12-quarter pull, so it contributes nothing; its scan movement is drift.)
- **28 pure window shifts** — `old[1:] == new[:-1]`, i.e. the series advanced by one
  quarter and a new value appended. **Structurally impossible for this fix to cause**: the
  change alters the basis of an existing comparison, it cannot add a quarter. These are
  10-Qs filed between the 2026-08-07 baseline scan and this one, picked up by the live
  edgartools gap-fill. The local bulk dataset is unchanged (parquet mtimes all 2026-07-21),
  so the drift is entirely from the live leg.

**One anomaly investigated and cleared: PVLA.** Its newest margin moved in place
(-9230.2 -> -4784.9) and it is NOT in the affected set, so it did not fit either population.
Tested directly by pulling it with the fix and with pre-fix behaviour restored in memory:
**byte-identical across every payload field.** The fix does not touch PVLA; it is drift on
the live leg, the same cause as the 28, in a different shape (a value revision rather than
a window advance). Recorded rather than waved through, since an unexplained in-place change
is exactly what the zero-tolerance rule exists to catch.

**DINO's scan row confirms the guard end-to-end:** `red`, `rev_yoy -0.6;11.8;53.1`,
`margin -0.4;9.1;8.6` — unchanged from baseline, and DINO does not appear in the mover list
at all.

### DEFERRED — two follow-ups found here, neither fixed

**1. `edgartools` fills are outside the restatement mechanism entirely — larger than this
gap.** `source == "edgartools"` is absent from `_RESTATEMENT_ELIGIBLE_SOURCES`, and not by
choice: `pipeline._fill_gaps` constructs those points AFTER `get_quarterly_series` has
already run `_attach_restatement_flags`, so they are never offered to it at all. Fixing it
means moving or re-running the flagger, not adding a source string. **This hits the NEWEST
quarters — the ones inside the scoring window** — which makes it higher-risk than the
derived-Q4 gap this entry closes. Needs its own investigation.

**2. A NaN `restated_value` breaks `/api/financials` for IDYA. PRE-EXISTING, not caused by
either of today's fixes.** — **CLOSED, FIXED same day; see "a NaN candidate was accepted as
a restatement, breaking IDYA outright" below.** Two things logged here turned out to
understate it: `/api/ticker` returned HTTP **500** as well, and the NaN was additionally
being counted as a valid rate by `_c33_status`, mis-scoring IDYA as `red` when it is
`insufficient`. Original note kept below as written.

A candidate row can carry `value = NaN`; `float(NaN) != point.value`
is True, so `restated=True` with `restated_value=NaN`, and `_yoy_value()` returns it
because `NaN is not None`. Result: `rev_yoy` carries NaN and the endpoint returns
`{"error":"Out of range float values are not JSON compliant: nan"}` instead of data.
- **Exactly 1 point universe-wide** — IDYA revenue 2024-09-30, out of 14,955 reported
  points. Zero derived points affected.
- **Dates to the GE fix (2026-08-02)**, when `_yoy_value` began consuming `restated_value`.
  Proven by reconstructing pre-fix behaviour in memory: at `b53835d` IDYA already carried
  NaN at `rev_yoy[3]` and `[5]` and already failed to serialise.
- The margin fix above adds a second NaN at `npm[1]` — it widens an already-broken payload
  but breaks nothing that worked.
- Likely fix is a `math.isnan` reject in the candidate walk, alongside the annual-mistag
  guard. Deliberately NOT bundled here: it is a different defect with its own blast radius,
  and this change is already at the edge of one commit's worth of verification.

---

## 2026-08-09 — a NaN candidate was accepted as a restatement, breaking IDYA outright

**Commit:** (this change) — `code33/quarterly_engine.py` only. **Closes the deferred item
logged in the derived-Q4 entry above.**

### What was wrong

`get_quarterly_series` runs `pd.to_numeric(num_df["value"], errors="coerce")`, so any
unparseable figure becomes NaN. `_attach_restatement_flags` then did:

```python
restated_value = float(latest_row["value"])
if restated_value != point.value:
```

**NaN != anything is True, including NaN != NaN.** So a NaN candidate silently satisfied
"differs from the point's own value" and was recorded as `restated=True` with
`restated_value=NaN`. `_yoy_value()` and `_restated_basis()` then accepted it, because both
test `is not None` — and NaN is not None.

### It was two defects, not one

**1. The payload could not be serialised at all.** Both endpoints were broken for IDYA:

```
/api/ticker/IDYA      http=500  {"error":"Out of range float values are not JSON compliant: nan"}
/api/financials/IDYA  http=200  {"error":"Out of range float values are not JSON compliant: nan"}
```

`/api/financials` is the worse of the two — HTTP **200** with an error body, so a caller
checking status codes sees success.

**2. The NaN was also scored as a real rate, and mis-ranked the ticker.** This is the part
the serialisation failure was hiding. `_c33_status`'s `_window()` filters on
`x is not None`, and **NaN is not None**, so a NaN counted toward `_MIN_RATES = 3`. The
scan checkpoint recorded it literally:

```
IDYA,red,nan;78.4;nan,57.4;-1502.1;-1269.6,
```

IDYA was scored **red** off a window of two phantom rates. With the NaN gone it has only
2 real YoY rates, is correctly **not scoreable**, and returns `insufficient` with a real
`excluded_reason` ("no reported revenue in 6 of 12 quarters — net margin and YoY are
undefined against a zero base"). IDYA is IDEAYA Biosciences, pre-revenue in most of the
window, so `insufficient` is the right answer and `red` never was.

### The fix

New `_is_unusable_candidate_value()` using `math.isnan` **explicitly**, rather than leaving
it to the `!=` comparison — that comparison is the exact mechanism that let this through.
Applied to candidates **before** the latest-filed sort, immediately ahead of the
annual-mistag guard and for the same reason: an unreadable row is not a weaker observation
of the quarter, it is no observation at all, so a genuine earlier restatement behind it
must still be able to win.

Same principle as the `point.value is None` / `point.tag is None` guards already there: a
missing input is not evidence of a restatement.

### Scope — measured across all 606 tickers BEFORE implementing

```
points checked           : 19,215   (both eligible sources, both metrics)
candidate sets examined  : 12,010
POINT_VALUE_NAN          : 0        <- no point's own .value can be NaN
NaN candidate sets       : 1
  NaN wins sort (live)   : 1
  NaN loses sort (latent): 0
  by source              : reported
```

The single case: **IDYA / revenue / 2024-09-30**, `point_value = 0.0`, whose sole candidate
(adsh `0001193125-25-264632`) is NaN.

**Zero latent cases** — there is no NaN candidate anywhere that currently loses the
latest-filed sort and would surface when a newer filing lands. That was the specific risk
worth measuring, since a losing candidate is invisible today.

**This is the only path a NaN can enter.** Confirmed by reading every consumer of the
coerced value column and then proven empirically by `POINT_VALUE_NAN: 0`:

| consumer | guard | safe? |
|---|---|---|
| `_best_tag_value` | `pd.notna(...)` before returning | yes — `point.value` can never be NaN |
| derived Q4 (`fy_value - sum(q_values)`) | operands come from `_best_tag_value` | yes — arithmetic on NaN-free inputs |
| `edgar_fill._facts` | `dropna(subset=[..., "numeric_value"])` | yes |
| `_attach_plausibility` | reads `point.value` only | yes, transitively |
| `_attach_restatement_flags` | **none** | **no — the hole** |

**On derived points specifically** (worth stating, since they became eligible for
restatement detection in the commit above): they are **not** a second entry path for a NaN
`point.value`, because the derivation is arithmetic over `_best_tag_value` output. They
*are* equally exposed on the `restated_value` side, through the same unguarded
`float(latest_row["value"])`, so one guard at the candidate level covers both sources.

### Verification

**Byte-level comparison, 34 tickers / 952 keys, zero tolerance.** Sample spans 8 green /
1 yellow / 9 red / 5 insufficient / 4 excluded_bank plus IDYA, DINO, MAGN, PAG, AAPL, GE,
JNJ. Baseline captured at `16b2fd0` with a clean engine tree.

```
tickers compared      : 34
keys compared         : 952
tickers with any diff : 1  ['IDYA']
  non-IDYA            : 0            <- zero unexplained movement
byte-identical        : 33
NaN sweep before      : IDYA {npm:[1], rev_restated_value:[4], rev_yoy:[3,5]}
NaN sweep after       : no NaN anywhere
```

**IDYA before → after**, and every change traces to removing the phantom restatement:

| field | before | after |
|---|---|---|
| `rev_yoy` | `[…, NaN, 78.43, NaN, …]` | `[…, -100.0, 78.43, null, …]` |
| `npm` | `[-865.54, NaN, -1861.6, …]` | `[-865.54, -1861.6, …]` |
| `rev_restated` | one `true` | all `false` |
| `rev_restated_value` | one `NaN` | all `null` |
| `status` | `red` | `insufficient` |
| `excluded_reason` | `""` | real diagnosis |

The two former NaN slots resolve **correctly** rather than merely vanishing: 2024-09-30 has
revenue `0.0` against a positive year-ago base, so **-100.0%** is right; 2025-09-30 compares
against that `0.0` base, so **null** is right — a zero base is genuinely not comparable.
15 IDYA fields are unchanged, including `rev`, `rev_end_dates`, `rev_sources` and
`rev_labels`, confirming no extracted value moved.

**Both endpoints confirmed fixed live over HTTP:** `/api/ticker/IDYA` 500 → **200**,
`/api/financials/IDYA` error-body → **8 real earnings quarters**, both parsing under a
strict JSON parser with `parse_constant` rigged to reject non-standard tokens, and zero
bare `NaN` tokens by word-boundary regex. Single listener confirmed (PID 5324); clean boot,
zero tracebacks.

**A full scan WAS run, deliberately.** The earlier judgement call — that a 1-point scope
makes a 606-ticker scan unnecessary — stopped being right the moment a status moved. This
is not the 2026-08-06 message-only case where nothing but text changed.

### Fresh full 606-ticker scan

Checkpoint archived as `ARCHIVED_pre_nanfix_scan_f6d3892accf3.csv.bak`; `resumed_from: 0`
confirmed on start. 606/606, breaker not tripped, no errors.

| status | before | after | delta |
|---|---|---|---|
| green | 9 | 9 | 0 |
| yellow | 1 | 1 | 0 |
| red | 419 | **418** | -1 |
| insufficient | 81 | **82** | +1 |
| excluded_bank | 96 | 96 | 0 |
| **TOTAL** | **606** | **606** | |

**Exactly one status change and exactly one value mover, both IDYA.** Zero window-shift
drift this run (it followed the previous scan closely enough that no new 10-Q landed), so
unlike the derived-Q4 scan there is no drift population to separate out — the single
in-place change is the entire delta.

```
before : IDYA,red,          nan;78.4;nan,   57.4;-1502.1;-1269.6,
after  : IDYA,insufficient, 0;-100.0;78.4,  57.4;-1502.1;-1269.6, no reported revenue (pre-revenue company)
```

`nan` appeared in the scan output for 1 ticker before and **0 after**. IDYA also now lands
in a named failure bucket instead of carrying an empty reason — the fix proving itself
through the scan path, not only the API path.

---

## 2026-08-10 — the annual mis-tag guard reached only half the pipeline

**Commit:** (this change) — `code33/edgar_fill.py` only.

Two separate outcomes in one investigation, deliberately kept apart: a **guard shipped**
(below), and a **restatement gap investigated and NOT built** (next section).

### PART 1 — annual mis-tag guard ported to the edgartools path (FIXED)

#### What was wrong

`_is_annual_mistagged_as_quarter` shipped in `16b2fd0` protects the **local-dataset** path
by testing a candidate against `num_q4`. The **edgartools gap-fill** path has no `num_q4`
and had no equivalent, so `fetch_discrete_quarter` would return a mis-tagged annual figure
as the **PRIMARY as-filed value** — not merely a restated one.

Two confirmed filer errors at SEC, both verified against `data.sec.gov`:

| ticker | accession | quarterly tag | annual twin | true scale error |
|---|---|---|---|---|
| DINO | `0001915657-26-000016` | 2024-10-01..2024-12-31 (91d) $28,580,000,000 | 2024-01-01..2024-12-31 (365d), identical | ~4x |
| AZZ | `0000008947-24-000044` | 2023-12-01..2024-02-29 (90d) $1,537,589,000 | 2023-03-01..2024-02-29 (365d), identical | ~4x |

**The existing SCALE GUARD cannot catch either.** It only demotes candidates *under*
1/100th of the series magnitude; an annual figure is several times too *large*.

#### Why it was invisible

Both quarters are currently supplied by the local dataset, so they arrive as
`derived_fy_minus_quarters` and the `16b2fd0` guard already protects them. The hazard is
live only when the bulk mirror lags over one of these quarters — the fill path is exactly
what covers that case. **Preventive, not a live defect: zero mis-tagged rows currently
reach a gap-filled point.**

#### The fix

`_is_annual_mistagged_as_quarter()` in `edgar_fill.py`, a near-mirror of the
`quarterly_engine` original with three shape differences: the comparison set is a new
`_ANNUAL_CACHE` (350-380 day rows) rather than `num_q4` (edgartools has no `qtrs` column);
identity is `accession`/`concept` rather than `adsh`/`tag`; and a zero value never counts.
Applied inside the per-tag loop, dropping rows **before** the `filing_date` sort — same
placement and reasoning as the original: a mis-tagged row is no observation of the quarter
at all, so a genuine row behind it must still be able to win.

`_load_facts_df` had to change to make this possible at all. It applied the 75-100 day
filter **before** caching, discarding every annual row (DINO: 5,720 raw -> 1,807 quarterly,
2,337 annual rows dropped), so the comparison set did not survive to where the guard needs
it. The split now happens before the quarter-length filter, populating `_ANNUAL_CACHE` from
the same already-fetched frame — **no extra network call**.

#### Two design points the measurement forced, both evidence-backed

- **`period_end` equality is load-bearing.** Across all 606 tickers the signature fires
  **98** times without it and **13** with it. The 85 extra are coincidental value matches
  against a different period. Two of them (GEO, MGTX) I initially reported as real hits and
  then disproved against SEC — SEC shows no annual row at those period_ends at all. That
  over-count was a defect in the probe, not in the data.
- **Zero values are excluded deliberately.** 6 of the 13 are `value == 0` on three
  pre-revenue filers (AMRX, DNTH, LASR) whose Q4 revenue and full-year revenue are both
  $0.00. `0 == 0` is arithmetic, not evidence. Rejecting it would push a legitimate $0.00
  filing into a gap and risk regressing the pre-revenue bucketing, which depends on $0.00
  filers keeping `value=0.0` (see the 2026-08-01 pre-revenue entry).

Net real population: **7 rows across 6 tickers** — DINO, AZZ (x2), OII, SPB, ZD, PBF — of
which only DINO and AZZ-2024 sit within ~12 quarters; the rest are 7-13 years old.

#### On returning None

Where the mis-tagged row is the **only** candidate in the window — true for both DINO and
AZZ — the guard rejects it and `fetch_discrete_quarter` returns `None`, leaving the quarter
unfilled. That is the correct trade: **a gap is honest, a 4x-wrong revenue value is not**,
and the pipeline already handles an unfilled quarter as a normal outcome. Verified directly
that no legitimate alternative row was being rejected in either window.

### PART 2 — edgartools restatement gap: INVESTIGATED, NOT BUILT

Closes the deferred item logged in `16b2fd0`. Same disposition as the LQDA sec-5 guard and
the insurance-tag sweep: mechanism real, failure mode occurs nowhere that matters, so the
machinery is deliberately not written.

#### The mechanism, confirmed exactly

```
get_complete_revenue_series (pipeline.py:181)
  |- get_quarterly_series
  |    |- _attach_restatement_flags   <- runs HERE
  |    |- return points[:quarters]
  |- _fill_gaps (pipeline.py:116)
       |- QuarterPoint(source="edgartools")   <- built AFTER
```

`QuarterPoint` defaults `restated=False` / `restated_value=None`, so edgartools points are
not merely unchecked — they carry a **positive assertion of "not restated" that nothing
computed**. `_yoy_value()` and `_restated_basis()` both fall through silently, and
`code33_adapter` publishes `false` for those quarters in `rev_restated` / `ni_restated`.
Nothing crashes; the contract is quietly wrong.

#### Why Option A (move the flagger after `_fill_gaps`) is a structural no-op

`_attach_restatement_flags` queries `num_df` — the **local parquet dataset**. An edgartools
point exists precisely *because that quarter is absent from it*. Measured: of **1,961**
edgartools points across **548** tickers, **1,940 (98.9%) have zero `qtrs=1` local rows**.
And the 21 that do have local rows **all agree** — so moving the flagger would add a second
pass and catch **zero** of the real hits.

#### Scope, triaged against `data.sec.gov`

**5 disagreements out of 1,961 points**, on **3 tickers — RBCAA, SHBI, PEBO — all
`excluded_bank`, none scored.** All sub-3%: +0.41%, +2.82%, +1.56%, -0.25%, -0.02%. SHBI's
2023-09-30 even carries a real 10-Q/A. **Live impact: zero.**

#### Why the count is 5 and not larger — self-limiting by construction

A restatement requires a *later* filing. For a freshly-filled newest quarter that filing
does not exist yet, and by the time it does the bulk mirror has caught up and the point
becomes `reported`, which **is** checked. So the gap bites only quarters both old enough to
have been restated and still missing locally. Age distribution: 854 points <=120d, 921 at
121-210d, 23 at 211-400d, **163 >400d** — and **all 5 hits are >400d**.

#### The tripwire for revisiting

Of the 163 old-backfill points, **18 sit on scored (non-bank) tickers across 10 tickers,
and zero of them disagree**. Rebuild the case if either changes:
- any of that scored residue ever shows a real disagreement, or
- the bulk-dataset lag grows, pushing more points into the >400d bucket.

Option B (detect inside `fetch_discrete_quarter`, where `.iloc[0]` is as-filed and
`.iloc[-1]` is the later figure — both already in hand) remains the right shape if it is
ever warranted. It would additionally need the scale guard extended to the `.iloc[-1]` row,
which today is applied only to the selected candidate: a filer correcting a units error
between filings — the documented PLXS thousands-vs-dollars class — would otherwise read as
a 1000x restatement.

#### Verification (guard)

**Byte-level whole-payload comparison, 49 tickers / 1,372 keys, zero tolerance.** Sample
deliberately weighted toward heavy edgartools users — 248 edgartools-sourced points across
the 49 — and spanning 7 green / 1 yellow / 28 red / 7 insufficient / 6 excluded_bank, with
DINO, AZZ and the other four mis-tag tickers (OII, SPB, ZD, PBF) plus AMRX/DNTH/LASR (the
zero-value cases) all pinned in.

```
tickers compared      : 49
keys compared         : 1372
tickers with any diff : 0
byte-identical        : 49
STATUS CHANGES        : 0
```

**Unit proof of the guard itself**, run directly against both confirmed cases:

```
DINO 2024-12-31 : RevenueFromContractWithCustomer...Excluding  91d  28,580,000,000  REJECTED
AZZ  2024-02-29 : RevenueFromContractWithCustomer...Excluding  90d   1,537,589,000  REJECTED
fetch_discrete_quarter(...) -> None in both cases
```

Inspected every candidate in both windows: the mis-tagged row is the ONLY one present, so
nothing legitimate is rejected and the fall-through has nothing to fall through to.

Single listener confirmed (PID 9540), clean boot, zero tracebacks. HTTP verified 200 on
`/api/ticker` and `/api/financials` for DINO, AZZ, IDYA, MAGN, AAPL.

#### No full 606-ticker scan — reasoning stated explicitly

Deliberately skipped, on the same basis as the 2026-08-06 message-only fix:

1. **The guard can only ever REMOVE a candidate.** It cannot invent, rescale or alter a
   value, so it has no mechanism to change a quarter that it does not reject.
2. **Universe-wide measurement already covers all 606 tickers**, not just the sample: of
   the 13 signature rows, **zero reach a gap-filled point**. The affected set is empty
   today by measurement, not by inference from a subsample.
3. **49/49 byte-identical**, including every ticker carrying the signature and the three
   zero-value filers the guard deliberately spares.

A scan would re-confirm what the signature census already established universe-wide. Run
one if the bulk-dataset lag ever grows enough to push a mis-tagged quarter into a fill
window — that is the condition under which this guard starts changing output.
