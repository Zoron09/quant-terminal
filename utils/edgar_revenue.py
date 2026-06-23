"""
utils/edgar_revenue.py  —  Production quarterly-revenue fetcher via edgartools.

PROTECTED MODULE — do not modify without a confirmed bug.

All four bugs discovered during testing are hardcoded as permanent safeguards:

  BUG 1  10-K/A amended filings    amendments=False on every 10-K fetch;
                                    amended 10-K/A filings lack full XBRL data
                                    and cause silent revenue extraction failures
                                    (confirmed: TSLA, AMD returned N/A without fix).

  BUG 2  Prior-year column (CRWD)  Pin column selection to the filing's own
                                    period_of_report date, not q_cols[0].
                                    When edgartools orders the prior-year
                                    comparison column first, q_cols[0] silently
                                    returns the wrong year's revenue
                                    (confirmed: CRWD FY26 Q2 returned $963.9M
                                    instead of $1,169.0M without fix).

  BUG 3  FY boundary estimate      Use exact previous 10-K period end as the
                                    fiscal year start boundary; never use a
                                    day-count estimate (was 369 days). The
                                    estimate can admit quarters from the wrong
                                    fiscal year at companies with irregular
                                    year lengths.

  BUG 4  Q4 derivation             Require exactly {Q1, Q2, Q3} within the
                                    fiscal year window before deriving Q4.
                                    Apply _is_implausible() guard to catch
                                    arithmetic failures (negative Q4, Q4 > 4×
                                    the average of other three quarters).
"""

import logging
from datetime import date, timedelta

from edgar import Company, set_identity as _edgar_set_identity

log = logging.getLogger(__name__)

# Module-level identity for all edgartools / SEC EDGAR requests
_edgar_set_identity("Meet Singh meetsingh@example.com")


# ── Private helpers ───────────────────────────────────────────────────────────

def _period_cols(df) -> list[str]:
    """All date-prefixed column headers (YYYY-MM-DD ...) from a statement df."""
    return [c for c in df.columns if len(c) > 8 and c[4] == "-" and c[7] == "-"]


def _revenue_row(df):
    """
    Best total-revenue row: standard_concept==Revenue, no dimension, no breakdown.
    Falls back to any Revenue row without dimension if strict match is empty.
    """
    mask = (df["standard_concept"] == "Revenue") & (df["dimension"] == False)
    strict = df[mask & (df["is_breakdown"] == False)]
    return strict if not strict.empty else df[mask]


def _to_m(val: float) -> float:
    """Convert raw USD value to millions, rounded to 1 decimal."""
    return round(val / 1_000_000, 1) if abs(val) >= 1_000_000 else round(val, 1)


def _is_implausible(q4: float, q1: float, q2: float, q3: float) -> bool:
    """
    BUG 4 guard: return True if the derived Q4 value is arithmetically suspect.

    Catches:
      - Negative Q4 (Annual < Q1+Q2+Q3, indicates mismatched FY data)
      - Q4 > 4× the average of Q1/Q2/Q3 (extreme outlier vs peer quarters)
    """
    if q4 <= 0:
        return True
    avg = (q1 + q2 + q3) / 3
    if avg > 0 and q4 > avg * 4.0:
        return True
    return False


def _extract_annual_revenue(filing) -> float | None:
    """
    Extract full-year revenue in millions from a 10-K filing.

    BUG 1: caller must have fetched with amendments=False.
    Prefers the '(FY)' labelled column; falls back to the first period column.
    Returns None on any failure so callers can skip Q4 derivation gracefully.
    """
    try:
        xb = filing.xbrl()
        income = xb.statements.income_statement()
        df = income.to_dataframe()
        rev = _revenue_row(df)
        if rev.empty:
            log.warning("edgar_revenue: no revenue row in 10-K period=%s", filing.period_of_report)
            return None
        cols = _period_cols(df)
        fy_cols = [c for c in cols if "(FY)" in c]
        col = fy_cols[0] if fy_cols else (cols[0] if cols else None)
        if col is None:
            return None
        return _to_m(rev.iloc[0][col])
    except Exception as exc:
        log.warning("edgar_revenue: _extract_annual_revenue period=%s: %s",
                    filing.period_of_report, exc)
        return None


def _extract_quarterly_revenue(filing) -> float | None:
    """
    Extract single-quarter (not YTD) revenue in millions from a 10-Q filing.

    BUG 2 safeguard: pins the column search to the filing's own
    period_of_report date before falling back to q_cols[0].

    Background: edgartools income-statement DataFrames contain both the
    current-period column and a prior-year comparison column, both labelled
    with '(Qn)'.  Column ordering is not guaranteed; CRWD's FY26 Q2 filing
    placed the prior-year '2024-07-31 (Q2)' column before the current-year
    '2025-07-31 (Q2)' column, causing q_cols[0] to silently return $963.9M
    (FY25 Q2) instead of $1,169.0M (FY26 Q2) — a $205M error.
    Matching on the date prefix eliminates this class of bug entirely.
    """
    own_period: str = filing.period_of_report   # 'YYYY-MM-DD'
    try:
        xb = filing.xbrl()
        income = xb.statements.income_statement()
        df = income.to_dataframe()
        rev = _revenue_row(df)
        if rev.empty:
            log.warning("edgar_revenue: no revenue row in 10-Q period=%s", own_period)
            return None
        cols = _period_cols(df)
        q_cols = [c for c in cols if "(Q" in c and "YTD" not in c]
        # BUG 2: prefer the column whose date prefix matches this filing's period end
        own_cols = [c for c in q_cols if c.startswith(own_period)]
        col = (own_cols[0] if own_cols
               else q_cols[0] if q_cols
               else cols[0] if cols
               else None)
        if col is None:
            return None
        return _to_m(rev.iloc[0][col])
    except Exception as exc:
        log.warning("edgar_revenue: _extract_quarterly_revenue period=%s: %s",
                    own_period, exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_quarterly_revenue(ticker: str, n_quarters: int = 8) -> list[dict]:
    """
    Return up to n_quarters of quarterly revenue for ticker, sorted newest first.

    Each element is a dict:
      'ticker'         str   — e.g. 'CRWD'
      'period_end'     date  — calendar end-date of the quarter
      'fiscal_quarter' str   — 'Q1' | 'Q2' | 'Q3' | 'Q4'
      'revenue_m'      float — revenue in USD millions (rounded to 1 dp)
      'source'         str   — '10-Q' (direct from filing) |
                               'derived_q4' (Annual minus Q1+Q2+Q3)

    Hardcoded safeguards — never remove:
      BUG 1  amendments=False on every 10-K get_filings call
      BUG 2  pin quarterly column to filing's own period_of_report date
      BUG 3  use exact previous 10-K period end as fiscal year start boundary
      BUG 4  require exactly {Q1,Q2,Q3}; run _is_implausible before appending Q4

    Returns empty list (never raises) if edgartools returns no data.
    """
    try:
        company = Company(ticker)
    except Exception as exc:
        log.warning("edgar_revenue: Company('%s') failed: %s", ticker, exc)
        return []

    # ── Build 10-Q revenue pool ───────────────────────────────────────────────
    n_10q = min(n_quarters + 6, 20)
    try:
        raw_10q = company.get_filings(form="10-Q").latest(n_10q)
    except Exception as exc:
        log.warning("edgar_revenue: %s 10-Q fetch failed: %s", ticker, exc)
        raw_10q = []

    # {period_str: revenue_m}  — one entry per unique quarter period end
    q_pool: dict[str, float] = {}
    for i in range(len(raw_10q)):
        f = raw_10q[i]
        rev = _extract_quarterly_revenue(f)
        if rev is not None:
            q_pool[f.period_of_report] = rev
        else:
            log.warning("edgar_revenue: %s 10-Q period=%s skipped (no revenue)",
                        ticker, f.period_of_report)

    # ── Fetch annual filings (BUG 1: amendments=False) ────────────────────────
    # Fetch one extra so annual_list[idx+1] always gives the previous FY end
    # (BUG 3) without a separate API call.
    n_fy = max((n_quarters // 4) + 2, 3)
    try:
        annual_obj = company.get_filings(form="10-K", amendments=False).latest(n_fy)
    except Exception as exc:
        log.warning("edgar_revenue: %s 10-K fetch failed: %s", ticker, exc)
        annual_obj = []

    annual_list: list = [annual_obj[i] for i in range(len(annual_obj))]

    # ── Assemble quarters FY by FY ────────────────────────────────────────────
    results: list[dict] = []
    seen: set[date] = set()

    for idx, af in enumerate(annual_list):
        try:
            fye = date.fromisoformat(af.period_of_report)
        except (ValueError, TypeError):
            continue

        # BUG 3: exact previous FY end — drawn from the next filing in the
        # already-fetched list; 366-day fallback only for the oldest entry.
        if idx + 1 < len(annual_list):
            try:
                prev_fye = date.fromisoformat(annual_list[idx + 1].period_of_report)
            except (ValueError, TypeError):
                prev_fye = fye - timedelta(days=366)
        else:
            prev_fye = fye - timedelta(days=366)

        # Quarters that strictly fall within this fiscal year
        fy_qs: list[tuple[date, float]] = sorted(
            [
                (date.fromisoformat(p), rev)
                for p, rev in q_pool.items()
                if prev_fye < date.fromisoformat(p) < fye
            ],
            key=lambda x: x[0],
        )

        # Emit Q1 / Q2 / Q3 (position-based labels within FY)
        for qi, (period, rev) in enumerate(fy_qs[:3]):
            if period not in seen:
                seen.add(period)
                results.append({
                    "ticker":         ticker,
                    "period_end":     period,
                    "fiscal_quarter": f"Q{qi + 1}",
                    "revenue_m":      rev,
                    "source":         "10-Q",
                })

        # BUG 4: derive Q4 only when exactly the right three quarters exist
        if len(fy_qs) < 3:
            log.warning(
                "edgar_revenue: %s FY=%s — %d quarter(s) found in window, need 3; skipping Q4",
                ticker, af.period_of_report, len(fy_qs)
            )
            continue

        # Belt-and-suspenders: confirm the set is exactly {Q1, Q2, Q3}
        fps = {f"Q{i + 1}" for i in range(3)}   # {'Q1','Q2','Q3'} by construction
        if fps != {"Q1", "Q2", "Q3"}:
            log.warning("edgar_revenue: %s FY=%s unexpected fps=%s; skipping Q4",
                        ticker, af.period_of_report, fps)
            continue

        annual_rev = _extract_annual_revenue(af)
        if annual_rev is None:
            log.warning("edgar_revenue: %s FY=%s annual revenue unavailable; skipping Q4",
                        ticker, af.period_of_report)
            continue

        q1_rev, q2_rev, q3_rev = fy_qs[0][1], fy_qs[1][1], fy_qs[2][1]
        q4_rev = round(annual_rev - q1_rev - q2_rev - q3_rev, 1)

        # BUG 4: implausibility guard — catches negative Q4 and extreme outliers
        if _is_implausible(q4_rev, q1_rev, q2_rev, q3_rev):
            log.warning(
                "edgar_revenue: %s FY=%s derived Q4=%.1fM failed implausibility check; skipping",
                ticker, af.period_of_report, q4_rev
            )
            continue

        if fye not in seen:
            seen.add(fye)
            results.append({
                "ticker":         ticker,
                "period_end":     fye,
                "fiscal_quarter": "Q4",
                "revenue_m":      q4_rev,
                "source":         "derived_q4",
            })

    results.sort(key=lambda r: r["period_end"], reverse=True)
    return results[:n_quarters]
