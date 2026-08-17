"""Live-EDGAR gap filler (edgartools) — fallback/supporting source only, never primary.

Pulls a company's XBRL facts once per process (cached) and answers targeted
"give me the discrete quarter ending near this date" requests for whatever
quarters secfsdstools doesn't have yet — structurally, the bulk mirror lags
real filings, so the gap is usually (not always) the single newest quarter.

SEC requires a compliant identifying User-Agent on all API calls; set_identity
handles that here.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from edgar import Company, set_identity

log = logging.getLogger(__name__)

set_identity("Meet Singh monikaarya.work@gmail.com")

# Discrete ("three months ended") duration window, days. Fiscal quarters run
# 13 weeks (91d) but 52/53-week calendars and month-length wobble spread this.
_QUARTER_MIN_DAYS = 75
_QUARTER_MAX_DAYS = 100

# A fact's period_end must land within this many days of the requested target
# to count as that quarter. Needs to absorb two effects stacking: secfsdstools
# rounds ddates to the nearest month end (up to ~15d off the true period end,
# which EDGAR facts carry exactly), plus 52/53-week calendar drift. Quarters
# sit ~91 days apart, so 25d can never grab an adjacent quarter.
MATCH_TOLERANCE_DAYS = 25

_FACTS_CACHE: Dict[str, Optional[pd.DataFrame]] = {}

# Annual-duration rows, kept as a SEPARATE narrow slice alongside _FACTS_CACHE.
# _load_facts_df filters to 75-100 days before caching, so the quarterly frame
# cannot answer "is this value also the filer's annual figure?" — the rows needed
# for that test have already been thrown away by then. Populated in the same pass
# from the same already-fetched frame: no extra network call, and narrowed to the
# revenue/NI concepts fetch_discrete_quarter actually selects from, so it stays a
# small fraction of the raw pull rather than a second full copy.
_ANNUAL_CACHE: Dict[str, Optional[pd.DataFrame]] = {}

# A fiscal year is ~365 days; the band absorbs 52/53-week calendars and leap years.
_ANNUAL_MIN_DAYS = 350
_ANNUAL_MAX_DAYS = 380


def _load_facts_df(ticker: str) -> Optional[pd.DataFrame]:
    """All duration-type facts for ticker as one dataframe, cached per process."""
    if ticker in _FACTS_CACHE:
        return _FACTS_CACHE[ticker]
    try:
        company = Company(ticker)
        facts = company.get_facts()
        # Deliberately no by_period_type("quarterly") here: edgartools' period
        # classifier silently drops some genuinely-quarterly rows (seen live:
        # DELL's newest 10-Q). The explicit 75-100 day duration filter below
        # is the real discrete-quarter test.
        df = facts.query().to_dataframe()
    except Exception as exc:
        log.warning("edgar_fill: facts pull failed for %s: %s", ticker, exc)
        _FACTS_CACHE[ticker] = None
        _ANNUAL_CACHE[ticker] = None
        return None

    if df is None or df.empty:
        _FACTS_CACHE[ticker] = None
        _ANNUAL_CACHE[ticker] = None
        return None

    df = df.copy()
    df["period_start"] = pd.to_datetime(df["period_start"], errors="coerce")
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df = df.dropna(subset=["period_start", "period_end", "numeric_value"])
    df["_days"] = (df["period_end"] - df["period_start"]).dt.days
    df = df[df["form_type"].isin(["10-Q", "10-K"])]

    # Split BEFORE the quarter-length filter — the annual rows are the comparison
    # set the mis-tag guard needs, and this is the only point at which both are
    # still in hand.
    _ANNUAL_CACHE[ticker] = df[
        (df["_days"] >= _ANNUAL_MIN_DAYS) & (df["_days"] <= _ANNUAL_MAX_DAYS)
    ]

    df = df[(df["_days"] >= _QUARTER_MIN_DAYS) & (df["_days"] <= _QUARTER_MAX_DAYS)]
    _FACTS_CACHE[ticker] = df
    return df


# Bank/depository-institution signal tags — STRONG signals only. Confirmed
# live (568-ticker scan): bare InterestIncomeExpenseNet/InterestRevenueExpenseNet
# are useless as bank signals — Delta, CVS, CSX, JB Hunt and ~65 other plain
# non-banks file them for nonoperating net interest. Genuine banks all carry
# at least one of these three: NoninterestIncome (bank-only vocabulary, and
# definitionally where the fee income that caused the FULT wrong-revenue bug
# lives), the bank top-line RevenuesNetOfInterestExpense, or a loan-loss
# provision line only lenders file. Deliberately NOT sector labels or ticker
# lists. REITs, insurers, and asset managers file none of these.
BANK_SIGNAL_TAGS = {
    "us-gaap:InterestIncomeExpenseAfterProvisionForLoanLoss",
    "us-gaap:NoninterestIncome",
    "us-gaap:RevenuesNetOfInterestExpense",
}


def bank_signal_tags(ticker: str) -> list:
    """The bank-signal tags this company actually files (empty list = not a
    bank, or facts unavailable — caller decides how to treat the latter)."""
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return []
    present = set(df["concept"].unique()) & BANK_SIGNAL_TAGS
    return sorted(t.split(":", 1)[1] for t in present)


# Income EARNED FROM LENDING. Every entry means the same economic thing; filers
# differ in which they use. This is deliberately NOT BANK_SIGNAL_TAGS: those three
# are only a "might be a bank" tripwire, and one of them (NoninterestIncome) is by
# definition the NON-lending part of a lender's income. Ratioing against that tag
# measured the wrong quantity and scored real lenders LOW — WRLD came out at 12.9%
# and ATLC at 0.1% when their actual lending share is 87% and 100%.
LENDING_INCOME_TAGS = [
    "us-gaap:InterestAndDividendIncomeOperating",      # standard bank total interest income
    "us-gaap:InterestAndFeeIncomeLoansAndLeases",
    "us-gaap:InterestAndFeeIncomeLoansConsumer",
    "us-gaap:InterestAndFeeIncomeLoansAndLeasesHeldInPortfolio",
    "us-gaap:InterestAndFeeIncomeLoansAndLeasesHeldForSale",
    "us-gaap:InterestAndFeeIncomeLoansCommercialAndIndustrial",
    "us-gaap:InterestAndFeeIncomeOtherLoans",
    "us-gaap:InterestIncomeOperating",
]

# Total-revenue denominators, best first.
_REVENUE_DENOMINATORS = [
    "us-gaap:Revenues",
    "us-gaap:RevenuesNetOfInterestExpense",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
]


def files_lending_income(ticker: str) -> bool:
    """Whether the company files ANY lending-income concept at all.

    Measured across all 100 excluded tickers: 97 file at least one, and every
    single bank-SIC ticker does. The 3 that file none (SKWD insurance, PLXS
    electronics, LOVE furniture retail) are exactly the false positives — their
    bank signal is a vestigial tag with no lending business behind it. So "files
    none" provably cannot describe a real bank.
    """
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return False
    return bool(set(df["concept"].unique()) & set(LENDING_INCOME_TAGS))


def lending_income_share(ticker: str) -> Optional[float]:
    """lending income / total revenue for the newest quarter carrying both.

    None when it cannot be computed (no lending concept, or no revenue concept) —
    the caller decides, and the safe reading of None is "cannot clear it".

    This is the measurement that actually separates a lender from a company with
    an incidental finance arm. Validated across all 100 excluded tickers: KMX
    lands at 5.8% and every genuine lender at 70.2% or above, with nothing in
    between — HASI is the closest at 68.5% and is correctly a lender.
    """
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return None
    lend = df[df["concept"].isin(LENDING_INCOME_TAGS)]
    if lend.empty:
        return None
    rev = df[df["concept"].isin(_REVENUE_DENOMINATORS)]
    if rev.empty:
        return None
    # Newest period_end where both sides have a fact, so the ratio compares one
    # quarter against itself rather than mixing periods.
    shared = sorted(set(lend["period_end"]) & set(rev["period_end"]), reverse=True)
    if not shared:
        return None
    period = shared[0]
    lend_v = lend[lend["period_end"] == period]["numeric_value"].max()
    rev_rows = rev[rev["period_end"] == period]
    rev_v = None
    for tag in _REVENUE_DENOMINATORS:
        hit = rev_rows[rev_rows["concept"] == tag]
        if not hit.empty:
            rev_v = float(hit["numeric_value"].iloc[0])
            break
    if not rev_v or rev_v <= 0 or lend_v is None:
        return None
    return float(lend_v) / rev_v


def has_xbrl_quarterly_facts(ticker: str) -> bool:
    """Whether SEC carries ANY discrete-quarter XBRL facts for this ticker.

    Only used to explain a dead end: when a CIK is absent from the local
    secfsdstools mirror, this separates "publishes no XBRL financial data at all"
    (royalty trusts, closed-end funds — PBT returns HTTP 404 on companyfacts)
    from "has XBRL at SEC but the local dataset lacks it", which is a genuinely
    different problem and the only one where a predecessor-CIK hunt makes sense.

    Deliberately reuses _load_facts_df, so it shares the per-process cache that
    bank_signal_tags() already populates for every ticker the adapter scores —
    on the normal path this costs no extra network call.
    """
    df = _load_facts_df(ticker)
    return df is not None and not df.empty


def _is_annual_mistagged_as_quarter(row, annual: pd.DataFrame) -> bool:
    """True when a candidate 'quarterly' row is really the filer's ANNUAL figure
    wearing a quarter-length period.

    Near-mirror of `quarterly_engine._is_annual_mistagged_as_quarter`, adapted to
    this data source. Same principle, three shape differences:
      - the comparison set is `_ANNUAL_CACHE` (350-380 day rows) rather than
        `num_q4`, because edgartools has no `qtrs` column;
      - identity is `accession` rather than `adsh`, and concept rather than tag;
      - a ZERO value never counts (see below).

    Real defect at SEC, not hypothetical, and it reaches the PRIMARY as-filed value
    on this path — not merely a restated one. Two confirmed cases:
      - DINO's FY2025 10-K tags $28,580,000,000 for 2024-10-01..2024-12-31 as a
        91-day quarter, bit-identical to the 365-day fact in the SAME filing.
      - AZZ's FY2024 10-K tags $1,537,589,000 as both a 90-day quarter
        (2023-12-01..2024-02-29) and the 365-day year, ~4x its true Q4.
    The existing SCALE GUARD cannot catch either: it only demotes candidates UNDER
    1/100th of series magnitude, and an annual figure is several times too LARGE.

    A fiscal year ends on the same date as its own Q4, so the annual fact shares the
    quarter's period_end — matching on it is what separates a real mis-tag from a
    coincidence. Measured across all 606 tickers: WITHOUT the period_end match the
    signature fires 98 times; WITH it, 13. That constraint is load-bearing, not
    decoration.

    ZERO IS EXCLUDED DELIBERATELY. 6 of those 13 are `value == 0` on three
    pre-revenue filers (AMRX, DNTH, LASR) whose Q4 revenue and full-year revenue are
    both $0.00. That is arithmetic, not evidence: a 0 == 0 match says nothing about
    mis-tagging, and rejecting it would push a legitimate $0.00 filing into a gap and
    risk regressing the pre-revenue bucketing (which depends on $0.00 filers keeping
    value=0.0 — see the 2026-08-01 pre-revenue entry in bug_report.md).

    Net real population: 7 rows across 6 tickers (DINO, AZZ x2, OII, SPB, ZD, PBF),
    of which only DINO and AZZ-2024 are within ~12 quarters. ZERO of them currently
    reach a gap-filled point, so this is preventive: it protects the primary value
    if the bulk dataset ever lags over one of these quarters.

    Exact value equality, deliberately NOT a magnitude ratio — the same discipline as
    the +/-1000% margin guard lesson: a threshold cannot separate a mis-tag from a
    real corporate action.
    """
    value = row["numeric_value"]
    if value == 0 or pd.isna(value):
        return False
    twin = annual[
        (annual["accession"] == row["accession"])
        & (annual["concept"] == row["concept"])
        & (annual["period_end"] == row["period_end"])
    ]
    return bool((twin["numeric_value"] == value).any())


# How far a period boundary may drift and still count as abutting its neighbour
# when the three known quarters are checked for tiling their fiscal year. Covers
# 52/53-week calendars and month-length wobble; far tighter than
# MATCH_TOLERANCE_DAYS because these are exact EDGAR period_starts/period_ends
# being compared against each other, not against a projected target date.
_FY_EDGE_TOLERANCE_DAYS = 20

# A derived Q4 may not exceed this multiple of the largest known quarter in its
# own fiscal year. Purely a units-consistency tripwire, and deliberately as loose
# as the existing SCALE GUARD's 1/100 bound is on the other side: it exists to
# catch the PLXS-class error where a filer tags the annual figure in thousands
# and the quarters in dollars (or vice versa), which lands ~1000x out. No real
# seasonal Q4 is 100x its own siblings.
_DERIVED_UNITS_SANITY_MULTIPLE = 100


def fetch_derived_fy_quarter(
    ticker: str,
    target_end: date,
    tag_priority: List[str],
    reference_magnitude: Optional[float] = None,
) -> Optional[Tuple[date, float, str, str, date, Optional[int], Optional[str], str]]:
    """A fiscal Q4 back-solved as FY_annual - (Q1 + Q2 + Q3), from live EDGAR facts.

    Returns (period_end, value, tag, accession, filing_date, fy, fp,
    derived_from_accessions) or None.

    WHY THIS EXISTS. Most filers never publish a discrete "three months ended"
    Q4 fact at all — the 10-K reports the full year, and Q4 is arithmetic. The
    bulk-dataset path already knows this and derives it (quarterly_engine's
    `derived_fy_minus_quarters` branch). The live fill did not: it only ever
    asked for a discrete quarter, so whenever the 10-K had been filed at SEC but
    had not yet reached the bulk mirror, the fiscal year-end quarter was simply
    left missing. That window is not small — DERA publishes the bulk data
    quarterly, so a February-year-end filer's April 10-K can be absent for
    months while its subsequent 10-Q is already being filled from live EDGAR,
    leaving a hole in the middle of the series.

    This mirrors quarterly_engine's derivation, sourced from _ANNUAL_CACHE
    instead of a local 10-K report object. It is a FALLBACK BEHIND A FALLBACK:
    _fill_gaps only calls it after fetch_discrete_quarter has already found
    nothing, so a real reported Q4 always wins, exactly as it does locally.

    COMPLETENESS IS STRUCTURAL, NOT COUNTED. The worst possible failure here is
    a partial subtraction: FY minus two quarters produces a number that looks
    entirely plausible and is badly wrong. Counting three rows is not enough to
    prevent that — three rows could be two quarters plus a restatement of one of
    them, or three quarters from overlapping periods. So the guard checks that
    the three quarters actually TILE the fiscal year:
      - the first quarter starts when the fiscal year starts;
      - each subsequent quarter starts where the previous one ended;
      - the leftover stub between the last known quarter and the fiscal year end
        is itself exactly one quarter long.
    Anything else and the quarter is left missing, which is what happens today
    and is always the safe answer.

    MIS-TAG GUARD INTERACTION — why this is not circular. `_ANNUAL_CACHE` is the
    comparison set for `_is_annual_mistagged_as_quarter`, and it is now also the
    source of the FY total. Those two uses never touch the same row:
      - the guard only fires when a QUARTER-length row shares its period_end
        with an annual row. By construction the three inputs here end strictly
        BEFORE the fiscal year end, so they cannot collide with the FY row.
      - the one row that could collide is a quarter-length row AT the fiscal year
        end — precisely the mis-tagged-annual case. That row is
        fetch_discrete_quarter's business, and if it existed and passed the guard
        this function would never have been called. If it existed and FAILED the
        guard, it was correctly rejected and deriving the quarter honestly from
        the annual total is the right answer, not a second bite at the bad row.
      - the annual row is never asked to validate itself: it is an input to
        arithmetic, not a candidate being screened.
    The guard is still applied to the three inputs below. It is expected to be a
    no-op for the reason above; it costs three row comparisons and means a filer
    doing something genuinely strange cannot slip a mis-tagged annual in as a Q1.

    NOT ATTACHED: plausibility and restatement flags. Both are computed inside
    get_quarterly_series, which has already returned by the time _fill_gaps runs,
    so — exactly like the existing `edgartools` fills since 2026-08-10 — points
    from this path carry `plausible=None` and an explicit `restated=False` that
    nothing computed. That is a known and documented limitation, not an
    assertion that the figure was checked and found un-restated.
    """
    df = _load_facts_df(ticker)
    annual = _ANNUAL_CACHE.get(ticker)
    if df is None or df.empty or annual is None or annual.empty:
        return None

    lo = pd.Timestamp(target_end - timedelta(days=MATCH_TOLERANCE_DAYS))
    hi = pd.Timestamp(target_end + timedelta(days=MATCH_TOLERANCE_DAYS))
    fy_window = annual[(annual["period_end"] >= lo) & (annual["period_end"] <= hi)]
    if fy_window.empty:
        return None

    edge = pd.Timedelta(days=_FY_EDGE_TOLERANCE_DAYS)

    for tag in tag_priority:
        concept = f"us-gaap:{tag}"
        fy_rows = fy_window[fy_window["concept"] == concept]
        if fy_rows.empty:
            continue
        # ORIGINAL as-filed wins, same rule as fetch_discrete_quarter: a later
        # filing's comparative column never replaces what the filing that owned
        # the period reported for it.
        fy_row = fy_rows.sort_values("filing_date").iloc[0]
        if pd.isna(fy_row["numeric_value"]):
            continue
        fy_value = float(fy_row["numeric_value"])
        fy_start, fy_end = fy_row["period_start"], fy_row["period_end"]

        # Same concept, quarter-length, wholly inside THIS fiscal year.
        inside = df[
            (df["concept"] == concept)
            & (df["period_start"] >= fy_start - edge)
            & (df["period_end"] <= fy_end + edge)
            & (df["period_end"] < fy_end - edge)
        ]
        if inside.empty:
            continue
        inside = inside[~inside.apply(
            lambda r: _is_annual_mistagged_as_quarter(r, annual), axis=1)]
        if inside.empty:
            continue

        # One row per distinct quarter end, earliest filing (as-filed) winning.
        picked = {}
        for _, r in inside.sort_values("filing_date").iterrows():
            picked.setdefault(r["period_end"], r)
        quarters = [picked[k] for k in sorted(picked)]

        if len(quarters) != 3:
            continue
        if any(pd.isna(q["numeric_value"]) for q in quarters):
            continue

        # --- the tiling guard -------------------------------------------------
        if abs((quarters[0]["period_start"] - fy_start).days) > _FY_EDGE_TOLERANCE_DAYS:
            continue
        if any(abs((b["period_start"] - a["period_end"]).days) > _FY_EDGE_TOLERANCE_DAYS
               for a, b in zip(quarters, quarters[1:])):
            continue
        remainder_days = (fy_end - quarters[-1]["period_end"]).days
        if not (_QUARTER_MIN_DAYS <= remainder_days <= _QUARTER_MAX_DAYS):
            continue
        # ----------------------------------------------------------------------

        q_values = [float(q["numeric_value"]) for q in quarters]
        derived = fy_value - sum(q_values)

        # UNITS SANITY, BOTH DIRECTIONS. See _DERIVED_UNITS_SANITY_MULTIPLE.
        #
        # Two distinct failure shapes, and an early version of this guard caught
        # only the first — found by its own adversarial test, not in review:
        #   (a) the QUARTERS are the small ones. Then the annual dominates and the
        #       derived figure comes out absurdly large: caught below.
        #   (b) the ANNUAL is the small one (tagged in thousands while the
        #       quarters are in dollars). Then `derived` is just -sum(quarters),
        #       which is quarter-sized and sails straight through a check on the
        #       derived value alone. It has to be caught on the INPUTS instead:
        #       a real fiscal year cannot be a hundredth of one of its own
        #       quarters.
        #
        # (b) deliberately errs toward refusing. A filer whose full-year figure is
        # genuinely under 1% of a single quarter — possible for net income when
        # large positive and negative quarters cancel — is left missing rather
        # than derived. That is the documented safe answer: a quarter that stays
        # absent costs coverage, a quarter derived from mismatched units puts a
        # plausible-looking wrong number into the scoring window.
        biggest = max(abs(v) for v in q_values) if any(q_values) else None
        if biggest and abs(fy_value) * _DERIVED_UNITS_SANITY_MULTIPLE < biggest:
            log.warning(
                "edgar_fill: %s %s annual %s is <1/%dth of its own largest quarter "
                "%s — suspected units mismatch, leaving missing",
                ticker, tag, fy_value, _DERIVED_UNITS_SANITY_MULTIPLE, biggest)
            continue
        if biggest and abs(derived) > _DERIVED_UNITS_SANITY_MULTIPLE * biggest:
            log.warning(
                "edgar_fill: %s derived %s Q4 %s is >%dx its own year's largest "
                "quarter %s — suspected units mismatch, leaving missing",
                ticker, tag, derived, _DERIVED_UNITS_SANITY_MULTIPLE, biggest)
            continue
        if reference_magnitude and abs(derived) > _DERIVED_UNITS_SANITY_MULTIPLE * abs(reference_magnitude):
            log.warning(
                "edgar_fill: %s derived %s Q4 %s is >%dx the series magnitude %s "
                "— suspected units mismatch, leaving missing",
                ticker, tag, derived, _DERIVED_UNITS_SANITY_MULTIPLE, reference_magnitude)
            continue

        fy_raw, fp_raw = fy_row.get("fiscal_year"), fy_row.get("fiscal_period")
        return (
            fy_end.date(),
            derived,
            tag,
            str(fy_row.get("accession") or ""),
            fy_row["filing_date"].date() if pd.notna(fy_row["filing_date"]) else target_end,
            int(fy_raw) if pd.notna(fy_raw) else None,
            str(fp_raw) if pd.notna(fp_raw) else None,
            ",".join(str(q.get("accession") or "") for q in quarters),
        )
    return None


def fetch_discrete_quarter(
    ticker: str,
    target_end: date,
    tag_priority: List[str],
    reference_magnitude: Optional[float] = None,
) -> Optional[Tuple[date, float, str, str, date, Optional[int], Optional[str]]]:
    """The discrete-quarter value ending nearest target_end (within tolerance).

    Returns (period_end, value, tag, accession, filing_date, fy, fp) or None.
    Tag priority mirrors the secfsdstools pull. Within a tag, the ORIGINAL
    as-filed figure wins (earliest filing_date) — same restatement principle as
    the primary source: later filings' comparative-column revisions never replace
    what the original filing reported for its own period.

    fy/fp come from the same selected row and are what let a gap-filled quarter
    carry a fiscal label instead of a blank one. They are only trustworthy
    BECAUSE of the earliest-filing_date rule above: edgartools stamps every fact
    with its FILING's fiscal year/period, so a quarter's own original 10-Q
    labels it correctly, while the comparative columns republished in later
    filings carry the later filing's fy/fp. Selecting the original filing avoids
    that mislabel by construction. Both degrade to None when absent or NaN — a
    blank label is the honest output, never a guessed one.
    """
    df = _load_facts_df(ticker)
    if df is None or df.empty:
        return None
    annual = _ANNUAL_CACHE.get(ticker)

    lo = pd.Timestamp(target_end - timedelta(days=MATCH_TOLERANCE_DAYS))
    hi = pd.Timestamp(target_end + timedelta(days=MATCH_TOLERANCE_DAYS))
    window = df[(df["period_end"] >= lo) & (df["period_end"] <= hi)]
    if window.empty:
        return None

    for tag in tag_priority:
        tag_rows = window[window["concept"] == f"us-gaap:{tag}"]
        if tag_rows.empty:
            continue

        # ANNUAL MIS-TAG GUARD. Near-mirror of quarterly_engine's
        # _is_annual_mistagged_as_quarter, adapted to this source's shape. Dropped
        # BEFORE the filing_date sort, exactly as that guard filters candidates
        # before picking the latest: a mis-tagged row is not a weaker observation
        # of the quarter, it is no observation of it at all, so a genuine row
        # behind it must still be able to win.
        if annual is not None and not annual.empty:
            tag_rows = tag_rows[~tag_rows.apply(
                lambda r: _is_annual_mistagged_as_quarter(r, annual), axis=1)]
            if tag_rows.empty:
                continue

        row = tag_rows.sort_values("filing_date").iloc[0]

        # SCALE GUARD. Filers sometimes tag one concept in thousands while tagging
        # a sibling concept for the SAME period in dollars. PLXS does exactly this
        # on 6 quarters: RevenueFromContractWithCustomerExcludingAssessedTax reads
        # 1,304,778 while ...IncludingAssessedTax reads 1,304,778,000 — identical
        # digits, 1000x apart. Excluding wins on tag priority, so the fill returned
        # a value 1000x too small and put a cliff in the middle of the series.
        #
        # Skipping the candidate (rather than rejecting the whole quarter) is the
        # point: priority then falls through to the next tag and recovers the
        # correctly-scaled figure, so the quarter is still filled.
        #
        # Self-limiting by construction: reference_magnitude is None until the
        # series already has established scale, so a first-quarter pull can never
        # trip this. The 1/100 bound is far looser than the 1000x errors seen —
        # a real quarter would have to collapse 99% to be caught, and the guard
        # only ever DEMOTES a candidate, never invents a value.
        # Universe-wide this signature appears on 3 of 606 tickers (PLXS 2026,
        # IRDM 2018, LUV 2011); the 7 other >=500x pairs are genuinely different
        # quantities, not scale errors, and are untouched by this.
        if reference_magnitude:
            value = float(row["numeric_value"])
            if value and abs(value) * 100 < abs(reference_magnitude):
                log.warning(
                    "edgar_fill: %s %s tag %s value %s is <1/100th of the series "
                    "magnitude %s — suspected units mismatch, trying next tag",
                    ticker, target_end, tag, value, reference_magnitude)
                continue

        fy_raw, fp_raw = row.get("fiscal_year"), row.get("fiscal_period")
        return (
            row["period_end"].date(),
            float(row["numeric_value"]),
            tag,
            str(row.get("accession") or ""),
            row["filing_date"].date() if pd.notna(row["filing_date"]) else target_end,
            int(fy_raw) if pd.notna(fy_raw) else None,
            str(fp_raw) if pd.notna(fp_raw) else None,
        )
    return None
