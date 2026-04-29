# Code 33 — Technical Specification
**Version:** 1.0  
**Last Updated:** April 29, 2026  
**Author:** Quant Terminal Project  
**Status:** Active — Ground Truth Document

---

## 1. Definition

Code 33 is Mark Minervini's fundamental acceleration filter. A stock qualifies when three core metrics show three consecutive quarters of accelerating growth simultaneously.

**Three metrics that must all accelerate:**
- EPS YoY% (Earnings Per Share, Year-over-Year growth)
- Revenue YoY% (Total Revenue, Year-over-Year growth)
- Net Profit Margin% (Net Income / Revenue)

**Mathematical condition:**
```
Q0 > Q-1 > Q-2 > Q-3
```
Where Q0 is the most recent quarter and Q-3 is the oldest. This must hold true for all three metrics simultaneously.

---

## 2. Data Requirements

### 2.1 Minimum Raw Quarters
- **8 raw quarters minimum** per metric
- 8 raw quarters produce 4 YoY% rates
- 4 YoY% rates produce 3 acceleration jumps
- 3 acceleration jumps = Code 33 signal

### 2.2 Why 8 and Not Less
- Each YoY% rate requires current quarter + same quarter prior year
- To get 4 YoY% rates: need 4 current quarters + 4 prior year quarters = 8 raw quarters
- With only 6 raw quarters you get 3 YoY rates = only 2 acceleration jumps = NOT enough for Code 33

### 2.3 Quarter Handling Rules
- **Never skip a quarter** — if a rate is unreliable, mark it as None but keep the quarter in the pool
- Skipping quarters reduces the raw quarter count below 8 and produces INSUFFICIENT
- INSUFFICIENT is never acceptable for a US-listed ticker with SEC filings — it always means a bug

---

## 3. Signal Definitions

| Signal | Condition |
|--------|-----------|
| **ACTIVE** | All three metrics show 3 consecutive acceleration jumps |
| **BROKEN** | Was ACTIVE but deceleration detected in any metric |
| **NOT ACTIVE** | Sufficient data but acceleration not present |
| **INSUFFICIENT** | Less than 8 raw quarters — always a bug, never acceptable |
| **NOT APPLICABLE** | Pre-profit company (negative EPS throughout) |

---

## 4. Data Sources & Priority

### 4.1 Ground Truth
**TradingView Financials (FactSet-sourced) = single source of truth.**
No other source overrides TradingView. Maximum acceptable deviation: 1%.

### 4.2 EPS Data Pipeline
**Source:** SEC EDGAR XBRL CompanyFacts API — standalone quarterly only

**Priority:**
1. Compute EPS = NetIncomeLoss / split-adjusted WeightedAverageNumberOfDilutedSharesOutstanding
2. Never use raw EarningsPerShareDiluted (rounded to 2 decimals, causes precision errors)
3. Never use YTD cumulative derivation (Annual minus 9-month = mathematically unreliable)
4. Never use yfinance or Finnhub EPS (adjusted/non-GAAP, does not match TradingView)

**Normalization Pipeline (Opus-designed):**
1. Fetch NetIncomeLoss standalone quarterly from EDGAR (latest-filed per quarter)
2. Fetch WeightedAverageNumberOfDilutedSharesOutstanding standalone quarterly from EDGAR (earliest-filed per quarter — pre-split original count)
3. Get cumulative split factor from yfinance using PERIOD END DATE (not filing date)
4. Adjust shares: shares_adj = shares_as_filed × cumulative_split_factor
5. Recompute EPS: EPS_adj = NetIncomeLoss / shares_adj
6. Apply N/A guards (see Section 5)

### 4.3 Revenue Data Pipeline
**Source:** FMP | EDGAR  
**Status:** Not yet fully validated against TradingView  
**Priority:** FMP primary, EDGAR fallback

### 4.4 Net Profit Margin Pipeline
**Source:** FMP | EDGAR  
**Status:** Not yet fully validated against TradingView  
**Calculation:** Net Income / Total Revenue per quarter

---

## 5. N/A Guards

These guards mark a YoY% rate as None but NEVER remove the quarter:

| Condition | Action |
|-----------|--------|
| abs(prior EPS) < 0.03 | rate = None, quarter stays |
| abs(YoY%) > 999% | rate = None, quarter stays |
| Sign flip (prior < 0, curr > 0 or vice versa) | rate = computed but label flagged [NM] |

**Critical:** None rates count toward the 8 raw quarter minimum. The quarter exists even if the rate is None.

---

## 6. Known Data Limitations

| Issue | Root Cause | Status |
|-------|-----------|--------|
| FactSet EPS differs by $0.01-0.02 | FactSet proprietary share normalization | Accepted — not fixable without FactSet ($500/mo) |
| Distorted base quarters | Near-zero or negative prior EPS amplifies small differences | Handled by N/A guard |
| EDGAR filing lag | Most recent quarter not yet filed | Expected — show fewer quarters, not INSUFFICIENT |
| Foreign/micro-cap tickers | Not in EDGAR XBRL | ERROR status, not INSUFFICIENT |

---

## 7. Tool Hierarchy

All decisions must follow this order:

1. **Methodology questions** → NotebookLM first
2. **General confirmation** → Perplexity
3. **Major decisions** → Explain to user in simple terms, get approval, then Opus
4. **Execution** → Ruflo / Claude Code

---

## 8. Engineering Rules

- One change at a time — regression test after every change
- Never touch confirmed working code without explicit approval
- No per-ticker patches — all fixes must be systemic
- Every confirmed working state committed to git before new change
- Commit message must include what was validated and version number
- Regression testing: always random tickers, minimum 20 tickers per run
- When tools die or context runs out: commit working state, document what's pending

---

## 9. Fiscal Year Edge Cases

| Case | Handling |
|------|---------|
| January FY-end (e.g. GIII) | Treat fy_end_month=1 as 12 for label assignment |
| Shifted EDGAR fy labels | Use date-proximity (±45 days from 365-day offset) for prior quarter matching, not fy-1 label |
| Stock splits | Apply cumulative split factor using period_end_date, not filing_date |
| Reverse splits | Same formula, yfinance returns factor < 1 |
| Class A/B shares | Use NI and diluted shares from same filing |

---

## 10. Acceptance Criteria

A Code 33 implementation is considered bulletproof when:

1. Zero tickers show INSUFFICIENT for US-listed companies with SEC filings
2. EPS YoY% matches TradingView within 1% for 95%+ of tickers
3. Revenue YoY% matches TradingView within 1% for 95%+ of tickers  
4. Net Margin% matches TradingView within 1% for 95%+ of tickers
5. Signal (ACTIVE/BROKEN/NOT ACTIVE) is always correct regardless of minor data variance
6. Random 20-ticker regression passes after every change
7. Accuracy audit on 100 random tickers shows 0% mismatch

---

## 11. Current Engine State

| Component | Version | Status |
|-----------|---------|--------|
| CACHE_VERSION | v19 | Last known stable |
| EPS Pipeline | NI/split-adjusted shares | Validated — 83% match, 0% mismatch |
| Revenue | FMP\|EDGAR | Not validated against TV |
| Net Margin | FMP\|EDGAR | Not validated against TV |
| Minimum quarters threshold | 7 (should be 8) | Known bug — needs fix |
| Quarter skipping | Active (should never skip) | Known bug — needs fix |

---

## 12. Pending Fixes (Priority Order)

1. Fix minimum quarters threshold from 7 to 8
2. Fix quarter skipping — mark None instead of removing quarter
3. Validate Revenue against TradingView
4. Validate Net Margin against TradingView
5. Fix CAMT/EDRY INSUFFICIENT bug (likely EDGAR fetch issue)
6. Run full 100-ticker accuracy audit after all fixes

---

*This document is the single source of truth for Code 33 implementation. Any deviation from this spec requires updating this document first.*
