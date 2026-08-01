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

### /api/ownership returns empty for EVERY ticker — OPEN, MEDIUM (found 2026-08-01)
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
