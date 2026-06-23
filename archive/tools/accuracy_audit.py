"""
Code 33 Engine Accuracy Audit — SEC EDGAR CompanyFacts reference source.
Independently fetches EarningsPerShareDiluted, recomputes YoY%, and compares
against engine output. Uses same _get_fq_fy labeling and fy_end_month as the
engine so fiscal-calendar labels align. Single-threaded, 0.5s EDGAR delay.
"""

import os, sys, json, random, requests, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('STREAMLIT_SERVER_HEADLESS', 'true')

import streamlit as st
st.cache_data = lambda *a, **kw: (lambda f: f)

from utils.code33_engine import get_code33_data, _get_fq_fy

# ── Config ────────────────────────────────────────────────────────────────────
SEED         = 42
SAMPLE_SIZE  = 100
MATCH_THRESH = 2.0
EDGAR_DELAY  = 0.5
OUT_FILE     = os.path.join(os.path.dirname(__file__), 'accuracy_audit.txt')
CSV_PATH     = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'Minervini_builder_Managed_2026-04-28.csv')
EDGAR_UA     = {'User-Agent': 'Meet Singh singhgaganmeet09@gmail.com'}

# ── CIK map ───────────────────────────────────────────────────────────────────
_CIK_MAP = {}

def load_cik_map():
    global _CIK_MAP
    if _CIK_MAP:
        return
    r = requests.get('https://www.sec.gov/files/company_tickers.json',
                     headers=EDGAR_UA, timeout=15)
    r.raise_for_status()
    for entry in r.json().values():
        tick = str(entry.get('ticker', '')).upper().strip()
        cik  = str(entry.get('cik_str', '')).zfill(10)
        if tick:
            _CIK_MAP[tick] = cik
    print(f'[cik map] loaded {len(_CIK_MAP)} tickers')

def get_cik(ticker: str) -> str | None:
    return _CIK_MAP.get(ticker.upper().strip())

# ── fy_end_month helper ───────────────────────────────────────────────────────
_FY_CACHE = {}

def get_fy_end_month(ticker: str) -> int:
    if ticker in _FY_CACHE:
        return _FY_CACHE[ticker]
    try:
        import yfinance as yf
        from datetime import timezone
        info = yf.Ticker(ticker).info or {}
        m = 12
        if 'lastFiscalYearEnd' in info:
            m = datetime.fromtimestamp(info['lastFiscalYearEnd'],
                                       tz=timezone.utc).month
        _FY_CACHE[ticker] = m
        return m
    except Exception:
        _FY_CACHE[ticker] = 12
        return 12

# ── EDGAR standalone EPS + YoY ────────────────────────────────────────────────
def edgar_eps_yoy(ticker: str, fy_end_month: int) -> dict:
    """
    Fetch EarningsPerShareDiluted standalone quarters from EDGAR and compute YoY%
    for the 3 most-recent quarters using the same _get_fq_fy labeling as the engine.
    Returns {label: {rate, curr, prior, curr_end, prior_end}}
    or {'_error': msg} / {'_insufficient': msg}.
    """
    time.sleep(EDGAR_DELAY)
    cik = get_cik(ticker)
    if not cik:
        return {'_error': f'CIK not found for {ticker}'}

    try:
        r = requests.get(
            f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
            headers=EDGAR_UA, timeout=15)
        r.raise_for_status()
        facts = r.json()
    except Exception as e:
        return {'_error': str(e)}

    entries = (facts.get('facts', {})
                    .get('us-gaap', {})
                    .get('EarningsPerShareDiluted', {})
                    .get('units', {})
                    .get('USD/shares', []))
    if not entries:
        return {'_insufficient': 'no EarningsPerShareDiluted/USD/shares data'}

    cutoff = (datetime.utcnow() - timedelta(days=365 * 5)).date()
    by_end = {}
    for e in entries:
        form = str(e.get('form', '')).upper()
        if form not in ('10-Q', '10-K', '20-F'):
            continue
        end_s, start_s, filed_s = (str(e.get(k, '')).strip()
                                   for k in ('end', 'start', 'filed'))
        val = e.get('val')
        if not end_s or not start_s or val is None:
            continue
        try:
            end_dt   = datetime.strptime(end_s,   '%Y-%m-%d').date()
            start_dt = datetime.strptime(start_s, '%Y-%m-%d').date()
            filed_dt = datetime.strptime(filed_s, '%Y-%m-%d').date() if filed_s else None
        except Exception:
            continue
        if end_dt < cutoff:
            continue
        if not (75 <= (end_dt - start_dt).days <= 105):
            continue
        if end_s not in by_end or (filed_dt and by_end[end_s]['filed']
                                   and filed_dt > by_end[end_s]['filed']):
            by_end[end_s] = {'end': end_dt, 'val': float(val), 'filed': filed_dt}

    if len(by_end) < 4:
        return {'_insufficient': f'only {len(by_end)} standalone quarters (need >=4)'}

    rows = sorted(by_end.values(), key=lambda x: x['end'], reverse=True)

    pairs = {}
    for curr in rows[:3]:
        try:
            target = curr['end'].replace(year=curr['end'].year - 1)
        except ValueError:
            target = curr['end'] - timedelta(days=365)
        best = None; best_diff = 46
        for cand in rows[3:]:
            d = abs((cand['end'] - target).days)
            if d < best_diff:
                best_diff = d; best = cand
        if best is None or best['val'] == 0:
            continue
        rate  = (curr['val'] - best['val']) / abs(best['val']) * 100
        # Use same labeling function as the engine — aligned to fiscal calendar
        label = _get_fq_fy(curr['end'], fy_end_month)
        if label:
            pairs[label] = {
                'rate':      rate,
                'curr':      curr['val'],
                'prior':     best['val'],
                'curr_end':  curr['end'].isoformat(),
                'prior_end': best['end'].isoformat(),
            }

    if not pairs:
        return {'_insufficient': 'no YoY pairs computable'}
    return pairs

# ── Per-ticker audit ──────────────────────────────────────────────────────────
def audit_ticker(ticker: str, idx: int, total: int) -> dict:
    result = {'ticker': ticker, 'status': None,
              'quarters': 0, 'max_diff': None, 'avg_diff': None, 'details': []}
    try:
        fy_end_month = get_fy_end_month(ticker)
        eng_data     = get_code33_data(ticker)
        edgar_data   = edgar_eps_yoy(ticker, fy_end_month)

        if '_error' in edgar_data:
            result['status'] = 'ERROR'
            result['details'].append(edgar_data['_error'])
            return result
        if '_insufficient' in edgar_data:
            result['status'] = 'INSUFFICIENT'
            result['details'].append(edgar_data['_insufficient'])
            return result

        eng_labels = eng_data.get('eps_labels', [])
        eng_yoy    = eng_data.get('eps_yoy',    [])
        if not eng_yoy:
            result['status'] = 'INSUFFICIENT'
            result['details'].append('engine: no EPS YoY data')
            return result

        eng_map = dict(zip(eng_labels, eng_yoy))
        diffs   = []

        for qlabel, ref in edgar_data.items():
            if qlabel not in eng_map:
                result['details'].append(
                    f'{qlabel}: engine missing  edgar={ref["rate"]:+.2f}%'
                    f'  (edgar curr={ref["curr"]:+.4f}@{ref["curr_end"]}'
                    f'  prior={ref["prior"]:+.4f}@{ref["prior_end"]})')
                continue
            eng_rate = eng_map[qlabel]
            if eng_rate is None:
                result['details'].append(f'{qlabel}: engine null')
                continue
            diff = abs(eng_rate - ref['rate'])
            diffs.append(diff)
            flag = 'MATCH' if diff < MATCH_THRESH else 'MISMATCH'
            result['details'].append(
                f'{qlabel}: eng={eng_rate:+.2f}%  edgar={ref["rate"]:+.2f}%'
                f'  diff={diff:.2f}%  [{flag}]'
                f'  curr={ref["curr"]:+.4f}@{ref["curr_end"]}'
                f'  prior={ref["prior"]:+.4f}@{ref["prior_end"]}')

        if not diffs:
            result['status'] = 'INSUFFICIENT'
            result['details'].append('no label overlap')
            return result

        result['quarters'] = len(diffs)
        result['max_diff'] = max(diffs)
        result['avg_diff'] = sum(diffs) / len(diffs)
        result['status']   = 'MISMATCH' if any(d >= MATCH_THRESH for d in diffs) else 'MATCH'
        return result

    except Exception as e:
        import traceback as _tb
        result['status'] = 'ERROR'
        result['details'].append(_tb.format_exc().strip().splitlines()[-1])
        return result

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    import pandas as pd

    df      = pd.read_csv(CSV_PATH)
    tickers = df['Symbol'].dropna().str.strip().tolist()
    print(f'[source] {CSV_PATH} — {len(tickers)} tickers')

    rng    = random.Random(SEED)
    sample = rng.sample(tickers, min(SAMPLE_SIZE, len(tickers)))
    print(f'[audit]  sample={len(sample)}, seed={SEED}, single-threaded\n')

    load_cik_map()

    results = []
    for idx, ticker in enumerate(sample, 1):
        res = audit_ticker(ticker, idx, len(sample))
        results.append(res)
        md_str = ('%.2f%%' % res['max_diff']) if res['max_diff'] is not None else 'N/A'
        print(f'  [{idx:3d}/{len(sample)}] {ticker:<8s} {res["status"]:<12s}'
              f' q={res["quarters"]}  maxdiff={md_str:>8s}')

    counts    = {'MATCH': 0, 'MISMATCH': 0, 'INSUFFICIENT': 0, 'ERROR': 0}
    all_diffs = []
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
        if r['status'] in ('MATCH', 'MISMATCH') and r['avg_diff'] is not None:
            all_diffs.append(r['avg_diff'])

    total    = len(results)
    avg_diff = sum(all_diffs) / len(all_diffs) if all_diffs else 0.0

    summary_lines = [
        '=' * 70,
        'CODE 33 ENGINE ACCURACY AUDIT  (reference: SEC EDGAR CompanyFacts)',
        f'Run date  : {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'Source    : Minervini_builder_Managed_2026-04-28.csv ({len(tickers)} tickers)',
        f'Sample    : {total}  seed={SEED}',
        f'Threshold : MATCH if abs diff < {MATCH_THRESH}%',
        '=' * 70,
        f'Total tickers tested    : {total}',
        f'MATCH   (abs diff <2%)  : {counts["MATCH"]:4d}  ({counts["MATCH"]/total*100:.1f}%)',
        f'MISMATCH (abs diff>=2%) : {counts["MISMATCH"]:4d}  ({counts["MISMATCH"]/total*100:.1f}%)',
        f'INSUFFICIENT            : {counts["INSUFFICIENT"]:4d}  ({counts["INSUFFICIENT"]/total*100:.1f}%)',
        f'ERROR                   : {counts["ERROR"]:4d}  ({counts["ERROR"]/total*100:.1f}%)',
        f'Avg abs diff (matched)  : {avg_diff:.2f}%',
        '=' * 70,
    ]

    results.sort(key=lambda r: (
        {'MISMATCH': 0, 'MATCH': 1, 'INSUFFICIENT': 2, 'ERROR': 3}.get(r['status'], 9),
        -(r['max_diff'] or 0)
    ))
    detail_lines = ['\nPER-TICKER DETAIL (mismatches first, largest diff):\n']
    for r in results:
        md = ('%.2f%%' % r['max_diff']) if r['max_diff'] is not None else 'N/A'
        detail_lines.append(
            f'{r["ticker"]:<8s} {r["status"]:<12s} q={r["quarters"]}  maxdiff={md}')
        for d in r['details']:
            detail_lines.append(f'         {d}')

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary_lines + detail_lines))

    print('\n' + '\n'.join(summary_lines))
    print(f'\n[saved] {OUT_FILE}')

if __name__ == '__main__':
    main()
