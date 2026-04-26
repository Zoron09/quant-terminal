"""
tools/diagnose_eps.py
=====================
Diagnostic CLI -- prints, for a given ticker, the raw EPS data each source
returns BEFORE the engine merges them, then shows the final merged eps_pool
that _date_first_yoy uses with source attribution.

SECTION 1: Raw source tables (yfinance / Finnhub / FMP / EDGAR) + merged pool
SECTION 2: yfinance vs EDGAR quarter-level comparison report

Usage:
    cd "C:\\Users\\Meet Singh\\quant-terminal"
    python tools/diagnose_eps.py AXON
    python tools/diagnose_eps.py AXON ANET ADI

Output saved to: tools/diagnostic_output.txt
"""

import io
import os
import sys

# Force UTF-8 on Windows so non-ASCII chars in API responses don't crash.
# Must happen before any print() calls.
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
import numpy as np
from datetime import datetime, timedelta, timezone

# Bootstrap: add project root so utils can be imported without pip install.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

import yfinance as yf

# ==============================================================================
# API keys
# ==============================================================================
FMP_API_KEY = os.getenv('FMP_API_KEY', '')
FINNHUB_KEY = os.getenv('FINNHUB_API_KEY', '')
EDGAR_UA    = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

# ==============================================================================
# Small numeric helpers
# ==============================================================================

def _sf(v, default=None):
    if v is None:
        return default
    try:
        f = float(v)
        return default if np.isnan(f) else f
    except Exception:
        return default


def _get_fq_fy(dt, fy_end_m=12):
    try:
        shift     = 12 - fy_end_m
        shifted_m = dt.month + shift
        if shifted_m > 12:
            fy        = dt.year + 1
            shifted_m -= 12
        else:
            fy = dt.year
        fq = (shifted_m + 2) // 3
        return "Q%d %d" % (fq, fy)
    except Exception:
        return ""


def _get_fy_end_month(ticker):
    """Ask yfinance for the fiscal-year-end month."""
    try:
        info = yf.Ticker(ticker.upper()).info or {}
        if 'lastFiscalYearEnd' in info:
            fy_end_dt = datetime.fromtimestamp(info['lastFiscalYearEnd'], tz=timezone.utc)
            return fy_end_dt.month
    except Exception:
        pass
    return 12

# ==============================================================================
# Section 1 table printer  (pure ASCII)
# ==============================================================================

HEADER = (
    "%-18s %-16s %-12s %12s %-10s %-10s"
    % ("source", "period_end_date", "filed_date", "eps_value", "fy_label", "fp_label")
)
SEP = "-" * 80


def _print_row(source, period_end, filed, eps_val, fy_lbl, fp_lbl):
    filed_str = filed if filed else "N/A"
    eps_str   = "%+.4f" % eps_val if eps_val is not None else "N/A"
    print("%-18s %-16s %-12s %12s %-10s %-10s"
          % (source, period_end, filed_str, eps_str, fy_lbl, fp_lbl))


def _print_header(title):
    print("\n" + "=" * 80)
    print("  " + title)
    print("=" * 80)
    print(HEADER)
    print(SEP)

# ==============================================================================
# SOURCE 1 -- yfinance earnings_dates [Reported EPS]
# ==============================================================================

def fetch_yfinance_eps(ticker, fy_end_m):
    rows = []
    try:
        ed = yf.Ticker(ticker.upper()).earnings_dates
        if ed is None or ed.empty or 'Reported EPS' not in ed.columns:
            return rows
        df = ed[['Reported EPS']].dropna()
        df = df.sort_index(ascending=False).head(12)
        for ts, row in df.iterrows():
            try:
                dt  = ts.date() if hasattr(ts, 'date') else datetime.strptime(str(ts)[:10], '%Y-%m-%d').date()
                val = _sf(row['Reported EPS'])
                if val is None:
                    continue
                rows.append({
                    'source':   'yfinance',
                    'end':      dt.isoformat(),
                    'filed':    None,
                    'val':      val,
                    'fy_label': _get_fq_fy(dt, fy_end_m),
                    'fp':       '',
                })
            except Exception:
                continue
    except Exception as e:
        print("  [yfinance ERROR] %s" % e)
    rows.sort(key=lambda x: x['end'])
    return rows[-8:]

# ==============================================================================
# SOURCE 2 -- Finnhub /stock/earnings [actual]
# ==============================================================================

def fetch_finnhub_eps(ticker, fy_end_m):
    rows = []
    if not FINNHUB_KEY:
        print("  [Finnhub] No API key -- skipped")
        return rows
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/stock/earnings",
            params={'symbol': ticker.upper(), 'limit': 12, 'token': FINNHUB_KEY},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json() if isinstance(r.json(), list) else []
        for item in data:
            if not isinstance(item, dict):
                continue
            period = str(item.get('period', '')).strip()
            actual = _sf(item.get('actual'))
            if not period or actual is None:
                continue
            try:
                dt = datetime.strptime(period, '%Y-%m-%d').date()
            except Exception:
                continue
            rows.append({
                'source':   'Finnhub',
                'end':      dt.isoformat(),
                'filed':    None,
                'val':      actual,
                'fy_label': _get_fq_fy(dt, fy_end_m),
                'fp':       '',
            })
    except Exception as e:
        print("  [Finnhub ERROR] %s" % e)
    rows.sort(key=lambda x: x['end'])
    return rows[-8:]

# ==============================================================================
# SOURCE 3 -- FMP income-statement [epsDiluted]
# ==============================================================================

def fetch_fmp_eps(ticker, fy_end_m):
    rows = []
    if not FMP_API_KEY:
        print("  [FMP] No API key -- skipped")
        return rows
    try:
        r = requests.get(
            "https://financialmodelingprep.com/stable/income-statement",
            params={'symbol': ticker.upper(), 'period': 'quarter',
                    'limit': 12, 'apikey': FMP_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json() if isinstance(r.json(), list) else []
        for item in data:
            if not isinstance(item, dict):
                continue
            date_str = str(item.get('date', '')).strip()
            eps_val  = (_sf(item.get('epsDiluted'))
                        if item.get('epsDiluted') is not None
                        else _sf(item.get('eps')))
            fy  = item.get('fiscalYear') or item.get('calendarYear')
            fp  = str(item.get('period', '')).upper().strip()
            if not date_str or eps_val is None:
                continue
            try:
                dt     = datetime.strptime(date_str, '%Y-%m-%d').date()
                fy_int = int(fy) if fy is not None else None
            except Exception:
                continue
            rows.append({
                'source':   'FMP',
                'end':      dt.isoformat(),
                'filed':    None,
                'val':      eps_val,
                'fy_label': _get_fq_fy(dt, fy_end_m),
                'fp':       fp if fp in ('Q1', 'Q2', 'Q3', 'Q4') else '',
                'fy':       fy_int,
            })
    except Exception as e:
        print("  [FMP ERROR] %s" % e)
    rows.sort(key=lambda x: x['end'])
    return rows[-8:]

# ==============================================================================
# SOURCE 4 -- EDGAR EarningsPerShareDiluted
# ==============================================================================

def _get_cik(ticker):
    try:
        mapping = requests.get(
            'https://www.sec.gov/files/company_tickers.json',
            headers=EDGAR_UA, timeout=15,
        ).json()
        ticker_up = ticker.upper().split('.')[0]
        for entry in mapping.values():
            if entry.get('ticker', '').upper() == ticker_up:
                return str(entry['cik_str']).zfill(10)
    except Exception:
        pass
    return None


def fetch_edgar_eps(ticker, fy_end_m):
    rows = []
    if '.' in ticker:
        print("  [EDGAR] Skipped -- non-US ticker")
        return rows

    cik = _get_cik(ticker)
    if not cik:
        print("  [EDGAR] CIK not found for %s" % ticker)
        return rows

    try:
        r = requests.get(
            'https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json' % cik,
            headers=EDGAR_UA, timeout=20,
        )
        r.raise_for_status()
        facts = r.json()
    except Exception as e:
        print("  [EDGAR ERROR] %s" % e)
        return rows

    usgaap   = facts.get('facts', {}).get('us-gaap', {})
    concepts = ['EarningsPerShareDiluted', 'EarningsPerShareBasic']
    cutoff   = (datetime.utcnow() - timedelta(days=365 * 5)).date()

    by_end = {}
    for concept in concepts:
        entries = usgaap.get(concept, {}).get('units', {}).get('USD/shares', [])
        for e in entries:
            form      = str(e.get('form', '')).upper()
            end_str   = str(e.get('end',   '')).strip()
            start_str = str(e.get('start', '')).strip()
            filed_str = str(e.get('filed', '')).strip()
            val       = _sf(e.get('val'))

            if not end_str or not start_str or val is None:
                continue
            if form not in ('10-Q', '10-K'):
                continue

            try:
                end_dt   = datetime.strptime(end_str,   '%Y-%m-%d').date()
                start_dt = datetime.strptime(start_str, '%Y-%m-%d').date()
            except Exception:
                continue

            if end_dt < cutoff:
                continue

            duration = (end_dt - start_dt).days
            if not (80 <= duration <= 105):
                continue

            filed_dt = None
            try:
                if filed_str:
                    filed_dt = datetime.strptime(filed_str, '%Y-%m-%d').date()
            except Exception:
                pass

            fy_raw = e.get('fy')
            fp_raw = str(e.get('fp', '')).strip().upper()

            rec = {
                'source':   'EDGAR',
                'end':      end_str,
                'end_dt':   end_dt,
                'filed':    filed_dt.isoformat() if filed_dt else None,
                'filed_dt': filed_dt,
                'val':      float(val),
                'fy_label': _get_fq_fy(end_dt, fy_end_m),
                'fp':       fp_raw if fp_raw in ('Q1', 'Q2', 'Q3', 'Q4') else '',
                'fy':       int(fy_raw) if fy_raw is not None else end_dt.year,
            }

            if end_str not in by_end:
                by_end[end_str] = rec
            elif (filed_dt and by_end[end_str]['filed_dt']
                  and filed_dt > by_end[end_str]['filed_dt']):
                by_end[end_str] = rec

    rows = sorted(by_end.values(), key=lambda x: x['end'], reverse=True)[:8]
    rows.reverse()
    return rows

# ==============================================================================
# Merged pool -- replicates engine _date_first_yoy dedup logic
# ==============================================================================

def _make_pool(vals, ends, src_name):
    pool = []
    for v, e in zip(vals, ends):
        if v is None or e is None:
            continue
        try:
            dt = datetime.strptime(e, '%Y-%m-%d').date()
        except Exception:
            continue
        pool.append({'val': float(v), 'end': e, 'dt': dt, 'src': src_name})
    pool.sort(key=lambda x: x['dt'], reverse=True)
    deduped = []
    for entry in pool:
        if not any(abs((entry['dt'] - k['dt']).days) <= 45 for k in deduped):
            deduped.append(entry)
    return deduped


def build_merged_pool(yf_rows, fh_rows, fmp_rows, edgar_rows):
    """
    Mirror the engine's priority chain:
      yfinance >= 3 pts => primary, else Finnhub.
      EDGAR overrides primary when values differ > 1%.
    Returns (merged, chosen_primary_name).
    """
    yf_vals = [r['val'] for r in yf_rows]
    yf_ends = [r['end'] for r in yf_rows]
    fh_vals = [r['val'] for r in fh_rows]
    fh_ends = [r['end'] for r in fh_rows]

    if len([v for v in yf_vals if v is not None]) >= 3:
        primary_vals, primary_ends, primary_name = yf_vals, yf_ends, 'yfinance'
    else:
        primary_vals, primary_ends, primary_name = fh_vals, fh_ends, 'Finnhub'

    edgar_vals = [r['val'] for r in edgar_rows]
    edgar_ends = [r['end'] for r in edgar_rows]

    primary_pool = _make_pool(primary_vals, primary_ends, primary_name)
    edgar_pool   = _make_pool(edgar_vals,   edgar_ends,   'EDGAR')

    merged = list(primary_pool)
    for ep in edgar_pool:
        dup_idx = next(
            (i for i, m in enumerate(merged) if abs((ep['dt'] - m['dt']).days) <= 45),
            -1,
        )
        if dup_idx == -1:
            merged.append(dict(ep, src='EDGAR(gap)'))
        else:
            diff = (abs(ep['val'] - merged[dup_idx]['val'])
                    / max(abs(ep['val']), abs(merged[dup_idx]['val']), 1e-9))
            if diff > 0.01:
                merged[dup_idx] = dict(ep, src='EDGAR(override)')
            else:
                merged[dup_idx]['src'] += '[=EDGAR]'

    merged.sort(key=lambda x: x['dt'])
    if len(merged) > 8:
        merged = merged[-8:]
    for m in merged:
        try:
            m['fy_label'] = _get_fq_fy(m['dt'], 12)
        except Exception:
            m['fy_label'] = m['end']

    return merged, primary_name

# ==============================================================================
# Section 2 -- yfinance vs EDGAR comparison
# ==============================================================================

CMP_HDR = ("%-14s %13s %11s %8s  %-12s %-13s %-11s %s"
           % ("period_end", "yfinance_eps", "edgar_eps",
              "gap_%", "yf_date", "edgar_filed", "same_day?", "sign_match?"))
CMP_SEP = "-" * 94


def compare_yf_edgar(yf_rows, edgar_rows):
    """
    Match each EDGAR period-end entry to the nearest yfinance announcement
    date within a -30 to +120 day window (earnings are announced 30-75 days
    after period end).

    Returns list of match dicts sorted by EDGAR period_end, each containing:
      period_end, yf_date, yf_eps, edgar_eps, edgar_filed,
      gap_pct, same_day (bool|None), sign_match (bool)
    """
    matches  = []
    used_yf  = set()

    for er in edgar_rows:
        try:
            e_dt = datetime.strptime(er['end'], '%Y-%m-%d').date()
        except Exception:
            continue

        best_yf, best_diff = None, 9999
        for yr in yf_rows:
            if yr['end'] in used_yf:
                continue
            try:
                y_dt = datetime.strptime(yr['end'], '%Y-%m-%d').date()
            except Exception:
                continue
            diff = (y_dt - e_dt).days       # +ve => yf is after period-end
            if -30 <= diff <= 120:
                if abs(diff) < best_diff:
                    best_diff = abs(diff)
                    best_yf   = yr

        if best_yf is None:
            continue
        used_yf.add(best_yf['end'])

        yf_val    = best_yf['val']
        ed_val    = er['val']
        gap_pct   = abs(yf_val - ed_val) / max(abs(ed_val), 1e-9) * 100
        sign_match = (yf_val >= 0) == (ed_val >= 0)

        same_day        = None
        edgar_filed_str = er.get('filed')
        if edgar_filed_str:
            try:
                ef_dt    = datetime.strptime(edgar_filed_str, '%Y-%m-%d').date()
                yf_dt    = datetime.strptime(best_yf['end'],  '%Y-%m-%d').date()
                same_day = abs((yf_dt - ef_dt).days) <= 7
            except Exception:
                pass

        matches.append({
            'period_end':  er['end'],
            'yf_date':     best_yf['end'],
            'yf_eps':      yf_val,
            'edgar_eps':   ed_val,
            'edgar_filed': edgar_filed_str,
            'gap_pct':     gap_pct,
            'same_day':    same_day,
            'sign_match':  sign_match,
        })

    matches.sort(key=lambda x: x['period_end'])
    return matches


def print_comparison_report(ticker, yf_rows, edgar_rows):
    print("\n" + "#" * 80)
    print("  COMPARISON REPORT: %s  (yfinance vs EDGAR)" % ticker)
    print("#" * 80)

    matches = compare_yf_edgar(yf_rows, edgar_rows)

    if not matches:
        print("  No overlapping quarters found.")
        return

    print("\n" + CMP_HDR)
    print(CMP_SEP)

    for m in matches:
        gap_s  = "%7.1f%%" % m['gap_pct']
        sd_s   = ("True " if m['same_day'] else "False") if m['same_day'] is not None else "N/A  "
        sgn_s  = "True " if m['sign_match'] else "False"
        fld_s  = m['edgar_filed'] if m['edgar_filed'] else "N/A"
        print("%-14s %+13.4f %+11.4f %s  %-12s %-13s %-11s %s"
              % (m['period_end'], m['yf_eps'], m['edgar_eps'],
                 gap_s, m['yf_date'], fld_s, sd_s, sgn_s))

    # -- Summary stats ---------------------------------------------------------
    total      = len(matches)
    large_gap  = [m for m in matches if m['gap_pct'] > 5.0]
    n_large    = len(large_gap)

    # same_day=True with large gap => GAAP vs adjusted concept difference
    concept_diff = [m for m in large_gap if m['same_day'] is True]

    # same_day=False AND edgar_filed > yf_date => possible restatement
    restatement = []
    for m in large_gap:
        if m['same_day'] is not False:
            continue
        if not m['edgar_filed']:
            continue
        try:
            if (datetime.strptime(m['edgar_filed'], '%Y-%m-%d').date()
                    > datetime.strptime(m['yf_date'], '%Y-%m-%d').date()):
                restatement.append(m)
        except Exception:
            pass

    print("\n  --- Summary: %s ---" % ticker)
    print("  Total overlapping quarters : %d" % total)
    print("  Quarters with gap > 5%%    : %d" % n_large)
    if n_large:
        print("    Of those, same_day=True  : %d  [concept diff -- GAAP vs adjusted]"
              % len(concept_diff))
        print("    Of those, same_day=False AND edgar_filed > yf_date : %d  [restatement signal]"
              % len(restatement))

# ==============================================================================
# Entry point
# ==============================================================================

if __name__ == '__main__':
    tickers = [t.upper() for t in (sys.argv[1:] if len(sys.argv) > 1 else ['AXON', 'ANET', 'ADI'])]

    output_path = os.path.join(ROOT, 'tools', 'diagnostic_output.txt')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    class _Tee:
        """Write to two streams simultaneously."""
        def __init__(self, s1, s2):
            self.s1, self.s2 = s1, s2
        def write(self, data):
            self.s1.write(data)
            self.s2.write(data)
        def flush(self):
            self.s1.flush()
            self.s2.flush()
        def fileno(self):
            return self.s1.fileno()

    orig = sys.stdout

    # --------------------------------------------------------------------------
    # Phase 1: fetch all sources + print raw tables + merged pool
    # --------------------------------------------------------------------------
    buf1    = io.StringIO()
    fetched = {}          # cache so Phase 2 doesn't re-fetch

    sys.stdout = _Tee(orig, buf1)
    try:
        for t in tickers:
            fy_end_m   = _get_fy_end_month(t)
            print("\n" + "#" * 80)
            print("  TICKER: %s" % t)
            print("#" * 80)
            print("  Fiscal year-end month: %d" % fy_end_m)

            print("  Fetching yfinance earnings_dates ...", end='', flush=True)
            yf_rows = fetch_yfinance_eps(t, fy_end_m)
            print(" %d rows" % len(yf_rows))

            print("  Fetching Finnhub /stock/earnings ...", end='', flush=True)
            fh_rows = fetch_finnhub_eps(t, fy_end_m)
            print(" %d rows" % len(fh_rows))

            print("  Fetching FMP epsDiluted ...", end='', flush=True)
            fmp_rows = fetch_fmp_eps(t, fy_end_m)
            print(" %d rows" % len(fmp_rows))

            print("  Fetching EDGAR EarningsPerShareDiluted ...", end='', flush=True)
            edgar_rows = fetch_edgar_eps(t, fy_end_m)
            print(" %d rows" % len(edgar_rows))

            fetched[t] = dict(yf=yf_rows, fh=fh_rows, fmp=fmp_rows, edgar=edgar_rows)

            for label, rows in [
                ("SOURCE 1 -- yfinance  earnings_dates [Reported EPS]",  yf_rows),
                ("SOURCE 2 -- Finnhub   /stock/earnings [actual]",        fh_rows),
                ("SOURCE 3 -- FMP       epsDiluted",                      fmp_rows),
                ("SOURCE 4 -- EDGAR     EarningsPerShareDiluted",         edgar_rows),
            ]:
                _print_header("%s | %s" % (t, label))
                if not rows:
                    print("  (no data)")
                else:
                    for r in rows:
                        _print_row(r['source'], r['end'], r.get('filed'),
                                   r['val'], r.get('fy_label', ''), r.get('fp', ''))

            merged, primary = build_merged_pool(yf_rows, fh_rows, fmp_rows, edgar_rows)
            print("\n" + "=" * 80)
            print("  %s | FINAL MERGED eps_pool  (primary = %s)" % (t, primary))
            print("=" * 80)
            print("  yfinance >= 3 pts => primary; else Finnhub.")
            print("  EDGAR overrides if values differ >1%; fills gaps otherwise.")
            print(HEADER)
            print(SEP)
            if not merged:
                print("  (empty -- insufficient data)")
            else:
                for m in merged:
                    _print_row(m['src'], m['end'], None, m['val'],
                               m.get('fy_label', ''), '')
            print()
    finally:
        sys.stdout = orig

    # --------------------------------------------------------------------------
    # Phase 2: comparison report
    # --------------------------------------------------------------------------
    buf2 = io.StringIO()
    sys.stdout = _Tee(orig, buf2)
    try:
        print("\n" + "#" * 80)
        print("  SECTION 2 -- yfinance vs EDGAR COMPARISON REPORT")
        print("#" * 80)
        for t in tickers:
            print_comparison_report(t, fetched[t]['yf'], fetched[t]['edgar'])
    finally:
        sys.stdout = orig

    # --------------------------------------------------------------------------
    # Write output file (overwrite; both sections in one file)
    # --------------------------------------------------------------------------
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("EPS Diagnostic Output -- generated %s\n" % ts)
        f.write("Tickers: %s\n" % ', '.join(tickers))
        f.write("=" * 80 + "\n\n")
        f.write("SECTION 1 -- Raw source tables + merged pool\n")
        f.write("=" * 80 + "\n")
        f.write(buf1.getvalue())
        f.write("\n" + "=" * 80 + "\n")
        f.write("SECTION 2 -- yfinance vs EDGAR comparison\n")
        f.write("=" * 80 + "\n")
        f.write(buf2.getvalue())

    print("\n[DONE]  Full output saved to: %s" % output_path)
