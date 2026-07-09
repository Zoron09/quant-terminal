"""
Pre-flight checks for the Code33 GREEN scan shortlist.
====================================================
Runs against an already-computed get_code33_data() result and flags known-broken
data-quality patterns before a ticker's GREEN signal ships. Each detector returns
a human-readable flag reason (or None); run_preflight() aggregates all of them.

Detectors:
  1. INSUFFICIENT status for a US-listed ticker (CODE33_SPEC.md: never acceptable)
  2. Sub-viable latest-quarter revenue (YoY swings on a tiny base are noise)
  3. SEC-declared reporting currency other than USD
  4. Foreign private issuer, 20-F/40-F annual-only filer (no 10-Q ever exists —
     Code33's quarterly methodology structurally doesn't apply)
  5. Possible CIK discontinuity for a tracked-universe name (holdco reorg swapped
     in a new SEC registrant, e.g. BlackRock/BLK 2024 — real history exists, just
     under a different, now-renamed CIK)
  6. Ticker no longer resolves in SEC's current ticker map (renamed, delisted, or
     taken private — a watchlist maintenance issue, not a data/engine bug)
  7. Genuinely deregistered issuer (Form 15 filed AND no filings since, past a
     buffer — a bare Form 15 alone is not sufficient signal, see detector docstring)

Detector 3 makes one extra network call (edgartools, latest 10-Q's XBRL facts) —
on any failure it returns None (skip) rather than guess, since a false positive
here is worse than a missed catch. Detectors 4-7 share that same philosophy and
make direct data.sec.gov calls (see _fetch_sec_submissions below) — independent
of secfsdstools/edgartools, and independent of the quarter-identification logic
in utils/code33_engine.py (that logic's date math is confirmed correct; these
detectors instead catch identity-resolution problems upstream of it: foreign
filer type, CIK succession, stale ticker mapping, deregistration).

A "code label vs SEC-declared fiscal quarter" mismatch detector was built and
tested (meant to catch TRT's non-standard fiscal year) but removed: it also
fired on CMP, which has a non-Dec FYE (Sept 30) too and is a legitimate current
GREEN ticker — the label mismatch turned out to be a common, apparently
harmless cosmetic quirk for non-Dec-FYE filers in general, not a marker of a
real data bug. TRT is not caught by any detector here as a result — see the
xfail note in tests/test_preflight_checks.py.
"""

import json
import os
import re
from datetime import date, datetime

import requests

from utils.sec_edgar import get_cik

REVENUE_FLOOR = 2_000_000  # verified against AIP ($11.2M) / CMP ($202.9M) / MU ($3.69B) quarterly minimums

CIK_DISCONTINUITY_MIN_DAYS = 1095  # ~3 years — see check_cik_discontinuity docstring
DEREGISTRATION_SILENCE_DAYS = 200  # see check_deregistered docstring

_QUARTER_RE = re.compile(r"Q(\d)")
_SEC_UA = {'User-Agent': 'QuantTerminal preflight@quant-terminal.local'}
_UNIVERSE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'sp500_tickers.json')

_submissions_cache = {}
_tracked_universe = None


def _fetch_sec_submissions(ticker):
    """Raw SEC EDGAR submissions JSON for `ticker`, or None on any failure
    (bad ticker, no CIK, network error) — skip rather than guess."""
    if ticker in _submissions_cache:
        return _submissions_cache[ticker]
    result = None
    try:
        cik = get_cik(ticker)
        if cik:
            r = requests.get(f'https://data.sec.gov/submissions/CIK{cik}.json', headers=_SEC_UA, timeout=10)
            r.raise_for_status()
            result = r.json()
    except Exception:
        result = None
    _submissions_cache[ticker] = result
    return result


def _earliest_report_date(sub, cutoff_iso, max_pages=5):
    """Earliest filings.recent reportDate, paginating into SEC's archived
    filings.files[] pages (bounded to max_pages) only if what we've found so
    far isn't already older than cutoff_iso. Large filers (heavy Form 4/8-K
    volume) can have a 'recent' window that doesn't reach back far enough on
    its own — confirmed on BLK, which looked IPO-recent using 'recent' alone
    until pagination revealed the true (still recent) earliest date."""
    recent = sub.get('filings', {}).get('recent', {})
    dates = [d for d in recent.get('reportDate', []) if d]
    earliest = min(dates) if dates else None
    if earliest and earliest <= cutoff_iso:
        return earliest
    for fmeta in sub.get('filings', {}).get('files', [])[:max_pages]:
        try:
            r = requests.get(f"https://data.sec.gov/submissions/{fmeta['name']}", headers=_SEC_UA, timeout=10)
            r.raise_for_status()
            page = r.json()
        except Exception:
            break
        pdates = [d for d in page.get('reportDate', []) if d]
        if pdates:
            page_earliest = min(pdates)
            if earliest is None or page_earliest < earliest:
                earliest = page_earliest
        if earliest and earliest <= cutoff_iso:
            return earliest
    return earliest


def _load_tracked_universe():
    global _tracked_universe
    if _tracked_universe is None:
        try:
            with open(_UNIVERSE_PATH) as f:
                _tracked_universe = set(json.load(f))
        except Exception:
            _tracked_universe = set()
    return _tracked_universe


def check_insufficient_status(ticker, data):
    if data.get('is_us', True) and str(data.get('status', '') or '').lower() == 'insufficient':
        return "status is INSUFFICIENT for a US-listed ticker — spec says this is never acceptable (data pipeline gap)"
    return None


def check_revenue_floor(ticker, data, floor=REVENUE_FLOOR):
    rev = [v for v in (data.get('rev') or []) if v is not None]
    if not rev:
        return None  # no data at all — already caught by check_insufficient_status
    latest = rev[-1]
    if latest < floor:
        return f"latest quarterly revenue ${latest:,.0f} is below the ${floor:,.0f} sub-viability floor — YoY swings likely noise, not signal"
    return None


def _latest_10q_fact(ticker, concept, max_filings=4):
    """Fetch `concept` from the most recent 10-Q that has both DocumentPeriodEndDate
    and the requested concept. Returns (period_end, value) or (None, None)."""
    from edgar import Company, set_identity
    set_identity("QuantTerminal preflight@quant-terminal.local")

    company = Company(ticker)
    filings = company.get_filings(form='10-Q').head(max_filings)
    for f in filings:
        xbrl = f.xbrl()
        facts = xbrl.facts
        pe = facts.query().by_concept('dei:DocumentPeriodEndDate').to_dataframe()
        target = facts.query().by_concept(concept).to_dataframe()
        if len(pe) and len(target):
            return str(pe['value'].iloc[0])[:10], str(target['value'].iloc[0]).strip()
    return None, None


def check_reporting_currency(ticker, data):
    try:
        _, iso = _latest_10q_fact(ticker, 'dei:EntityReportingCurrencyISOCode', max_filings=2)
    except Exception:
        return None
    if iso and iso.upper() != 'USD':
        return f"SEC filing reports financials in {iso.upper()}, not USD — revenue/NI figures are foreign-currency, not directly comparable"
    return None


def check_foreign_annual_only(ticker, data):
    """Foreign private issuers (BIDU, BABA, ...) file 20-F/40-F annually and
    never file a 10-Q. Code33's quarterly-acceleration methodology has no
    quarters to work with for these — exclude rather than let them fall
    through as INSUFFICIENT."""
    sub = _fetch_sec_submissions(ticker)
    if not sub:
        return None
    forms = set(sub.get('filings', {}).get('recent', {}).get('form', []))
    if (forms & {'20-F', '40-F'}) and '10-Q' not in forms:
        return ("SEC filing history is 20-F/40-F annual-only, no 10-Q ever filed — "
                "Code33's quarterly-acceleration methodology structurally doesn't apply to this filer type")
    return None


def check_cik_discontinuity(ticker, data, min_days=CIK_DISCONTINUITY_MIN_DAYS):
    """Flags (does not auto-correct) the BlackRock/BLK-type case: a ticker we
    already treat as an established name (present in the tracked universe,
    data/sp500_tickers.json) whose *current* CIK has suspiciously little SEC
    history — a holdco reorg can swap in a brand-new registrant for an old
    ticker (confirmed: BLK's current CIK 2012383 only goes back to Feb 2024;
    the real 2006-2024 history sits under CIK 1364742, renamed by SEC itself
    to "BlackRock Finance, Inc." on 2024-09-26). Recovering the pre-reorg
    history is a separate, harder problem — this only flags for manual review
    so it isn't silently treated as INSUFFICIENT or a fresh listing.

    min_days=1095 (~3 years): long enough that a genuine recent IPO already
    in the tracked universe (e.g. ABNB, RIVN, LCID) won't false-positive past
    typical lockup/index-inclusion timelines, short enough to still catch a
    reorg without much delay — a soft manual-verify flag, not a hard exclusion,
    so erring toward a slightly longer window costs little."""
    if ticker.upper() not in _load_tracked_universe():
        return None
    sub = _fetch_sec_submissions(ticker)
    if not sub:
        return None
    cutoff = date.today().replace(year=date.today().year - min_days // 365)
    earliest = _earliest_report_date(sub, cutoff.isoformat())
    if not earliest:
        return None
    try:
        earliest_dt = datetime.strptime(earliest, '%Y-%m-%d').date()
    except ValueError:
        return None
    age_days = (date.today() - earliest_dt).days
    if age_days < min_days:
        return (f"tracked as an established name but earliest SEC filing on record is only "
                f"{earliest} ({age_days} days old) — possible CIK discontinuity (holdco reorg "
                f"swapped in a new registrant, e.g. BlackRock/BLK 2024) rather than a genuine "
                f"new listing; verify manually before treating as INSUFFICIENT")
    return None


def check_ticker_resolution(ticker, data):
    """Distinct failure mode from a generic data gap: the ticker doesn't
    resolve to any CIK in SEC's current company_tickers.json at all. Usually
    means the ticker was renamed (ABC -> COR/Cencora) or the company was
    delisted/taken private (WBA) — a watchlist maintenance issue, not an
    engine/data problem, so it should read differently from INSUFFICIENT."""
    try:
        cik = get_cik(ticker)
    except Exception:
        return None
    if cik is None:
        return ("ticker not found in current SEC records — likely renamed, delisted, or taken "
                "private (e.g. ABC->COR rename, WBA take-private); this is a watchlist "
                "maintenance issue, not a data/engine bug")
    return None


_OPERATING_FORMS = {'10-Q', '10-Q/A', '10-K', '10-K/A', '8-K', '8-K/A', '20-F', '20-F/A', '40-F', '40-F/A'}


def check_deregistered(ticker, data, silence_days=DEREGISTRATION_SILENCE_DAYS):
    """A Form 15 (15-12B/15-12G/15-15D) alone is NOT sufficient signal of
    deregistration — round-3 testing found 5 tickers (AME, CB, JNJ, LIN, TEAM)
    with one in their history that kept filing normally afterward (Form 15 can
    be filed administratively for a single securities class/plan without
    ending the company's reporting obligations entirely). Only flag when BOTH
    hold: a Form 15 exists, AND no *operating* filing (10-Q/10-K/8-K/20-F/40-F
    — the issuer reporting on itself) exists for silence_days afterward.

    Deliberately ignores non-operating forms (SC 13G/13D, DEF 14A, etc.) when
    measuring silence — those are frequently filed by third parties (e.g.
    institutional holders' ownership disclosures) and keep appearing under a
    dead CIK indefinitely regardless of whether the issuer itself still
    reports. First implementation used "most recent filing of any kind" and
    false-negatived on CPTP, whose real Form 15 (2025-02-11) was followed only
    by third-party SC 13G/DEF 14A filings, not by CPTP itself. Restricting to
    operating forms fixed it — confirmed CPTP has no 10-Q/10-K/8-K after its
    Form 15, ~17 months of silence as of today.

    silence_days=200 comfortably exceeds one quarterly cycle (~90 days) plus
    filing lag, so an administrative Form 15 followed by a normal next 10-Q
    never trips this, while a genuine stop does easily."""
    sub = _fetch_sec_submissions(ticker)
    if not sub:
        return None
    recent = sub.get('filings', {}).get('recent', {})
    forms = recent.get('form', [])
    filing_dates = recent.get('filingDate', [])
    form15_dates = sorted(fd for f, fd in zip(forms, filing_dates) if f.startswith('15-1') and fd)
    if not form15_dates:
        return None
    last_form15 = form15_dates[-1]
    post_dereg_operating = [
        fd for f, fd in zip(forms, filing_dates)
        if f in _OPERATING_FORMS and fd and fd > last_form15
    ]
    silence = (date.today() - datetime.strptime(last_form15, '%Y-%m-%d').date()).days
    if not post_dereg_operating and silence >= silence_days:
        return (f"Form 15 filed {last_form15} (deregistration/termination of reporting) with no "
                f"operating filings (10-Q/10-K/8-K/etc.) since ({silence} days of silence) — "
                f"genuinely deregistered, not a transient administrative gap")
    return None


def run_preflight(ticker, data):
    """Returns a list of human-readable flag reasons; empty list = clean."""
    checks = [
        check_insufficient_status(ticker, data),
        check_revenue_floor(ticker, data),
        check_reporting_currency(ticker, data),
        check_foreign_annual_only(ticker, data),
        check_cik_discontinuity(ticker, data),
        check_ticker_resolution(ticker, data),
        check_deregistered(ticker, data),
    ]
    return [c for c in checks if c]
