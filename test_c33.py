"""Test Code 33 rewrite against UCTT, WULF, TBBB, AAPL"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Minimal streamlit mock for caching
import streamlit as st

import importlib
M = importlib.import_module('pages.15_stock_detail')

def test_ticker(t):
    print(f"\n{'='*60}")
    print(f"TICKER: {t}")
    print(f"{'='*60}")
    c33 = M.get_code33_data(t)
    is_us = c33.get('is_us', '?')
    sources = c33.get('sources', {})
    eps = c33.get('eps', [])
    rev = c33.get('rev', [])
    ni  = c33.get('ni', [])
    eps_labels = c33.get('eps_labels', [])

    print(f"  is_us: {is_us}")
    print(f"  sources: {sources}")
    print(f"  EPS ({len(eps)}Q): {eps[-5:] if len(eps)>5 else eps}")
    print(f"  REV ({len(rev)}Q): {[f'{v/1e6:.0f}M' if v and abs(v)>1e6 else v for v in (rev[-5:] if len(rev)>5 else rev)]}")
    print(f"  NI  ({len(ni)}Q):  {[f'{v/1e6:.0f}M' if v and abs(v)>1e6 else v for v in (ni[-5:]  if len(ni)>5  else ni)]}")
    print(f"  labels: {eps_labels[-5:] if len(eps_labels)>5 else eps_labels}")

    # Pre-profit check
    if len(eps) >= 3:
        last3 = eps[-3:]
        is_pp = all(v is not None and v < 0 for v in last3)
        print(f"  pre-profit: {is_pp} (last 3 EPS: {last3})")

    # YoY
    eps_yoy = M._compute_yoy(eps)
    rev_yoy = M._compute_yoy(rev)
    print(f"  EPS YoY: {[f'{v:.1f}' if v else 'None' for v in eps_yoy]}")
    print(f"  REV YoY: {[f'{v:.1f}' if v else 'None' for v in rev_yoy]}")

    eps3 = M._last3_valid(eps_yoy)
    rev3 = M._last3_valid(rev_yoy)
    eps_status, eps_d1, eps_d2 = M._c33_status(eps3)
    rev_status, rev_d1, rev_d2 = M._c33_status(rev3)
    print(f"  EPS status: {eps_status} (d1={eps_d1}, d2={eps_d2})")
    print(f"  REV status: {rev_status} (d1={rev_d1}, d2={rev_d2})")

for t in ['GTE', 'WULF', 'UCTT', 'TBBB']:
    test_ticker(t)
