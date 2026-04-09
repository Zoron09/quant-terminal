"""
SQLite cache for screener results.
Stores pre-computed SEPA scores, technicals, fundamentals, and earnings.
All subsequent screener loads read from here for instant results.
"""
import sqlite3
import os
import time
import numpy as np
import pandas as pd
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'screener_cache.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS sepa_cache (
    ticker          TEXT PRIMARY KEY,
    name            TEXT,
    price           REAL,
    chg_pct         REAL,
    market_cap      REAL,
    pe              REAL,
    profit_margin   REAL,
    rev_growth      REAL,
    eps_growth      REAL,
    vol_ratio       REAL,
    volume          INTEGER,
    hi52            REAL,
    lo52            REAL,
    pct_from_hi     REAL,
    trend_pass      INTEGER,
    stage           INTEGER,
    stage_label     TEXT,
    rs_12m          REAL,
    vcp             INTEGER,
    sepa_score      REAL,
    sepa_grade      TEXT,
    earnings_status TEXT,
    market          TEXT,
    updated_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_sepa_score ON sepa_cache(sepa_score DESC);
CREATE INDEX IF NOT EXISTS idx_market     ON sepa_cache(market);
"""

COLS = [
    'ticker', 'name', 'price', 'chg_pct', 'market_cap', 'pe',
    'profit_margin', 'rev_growth', 'eps_growth', 'vol_ratio', 'volume',
    'hi52', 'lo52', 'pct_from_hi', 'trend_pass', 'stage', 'stage_label',
    'rs_12m', 'vcp', 'sepa_score', 'sepa_grade', 'earnings_status',
    'market', 'updated_at',
]


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.executescript(SCHEMA)
    con.commit()
    return con


def _safe(v):
    """Convert NaN/inf to None for SQLite storage."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return str(v) if v else None


def upsert_rows(rows: list[dict], market: str):
    """Bulk-upsert a list of row dicts into sepa_cache."""
    if not rows:
        return
    now = time.time()
    con = _conn()
    records = []
    for r in rows:
        records.append((
            str(r.get('ticker', '')).upper(),
            str(r.get('name', '') or r.get('ticker', '')),
            _safe(r.get('price')),
            _safe(r.get('chg_pct')),
            _safe(r.get('market_cap')),
            _safe(r.get('pe')),
            _safe(r.get('profit_margin')),
            _safe(r.get('rev_growth')),
            _safe(r.get('eps_growth')),
            _safe(r.get('vol_ratio')),
            int(r['volume']) if r.get('volume') else None,
            _safe(r.get('hi52')),
            _safe(r.get('lo52')),
            _safe(r.get('pct_from_hi')),
            int(r['trend_pass']) if r.get('trend_pass') is not None else None,
            int(r['stage'])      if r.get('stage')      is not None else None,
            str(r.get('stage_label', 'N/A')),
            _safe(r.get('rs_12m')),
            1 if r.get('vcp') else 0,
            _safe(r.get('sepa_score')),
            str(r.get('sepa_grade', 'D')),
            str(r.get('earnings_status', 'Pending')),
            market,
            now,
        ))
    placeholders = ','.join(['?'] * len(COLS))
    con.executemany(
        f"INSERT OR REPLACE INTO sepa_cache ({','.join(COLS)}) VALUES ({placeholders})",
        records,
    )
    con.commit()
    con.close()


def load_market(market: str) -> pd.DataFrame:
    """Load all rows for a market, return as DataFrame."""
    try:
        con = _conn()
        df = pd.read_sql_query(
            "SELECT * FROM sepa_cache WHERE market=? ORDER BY sepa_score DESC",
            con, params=(market,),
        )
        con.close()
        if not df.empty:
            df['vcp'] = df['vcp'].astype(bool)
        return df
    except Exception:
        return pd.DataFrame()


def freshness(market: str) -> Optional[float]:
    """Return seconds since last update for this market, or None if no data."""
    try:
        con = _conn()
        cur = con.execute(
            "SELECT MAX(updated_at) FROM sepa_cache WHERE market=?", (market,)
        )
        val = cur.fetchone()[0]
        con.close()
        return (time.time() - val) if val else None
    except Exception:
        return None


def clear_market(market: str):
    """Delete all rows for a market (before re-scan)."""
    try:
        con = _conn()
        con.execute("DELETE FROM sepa_cache WHERE market=?", (market,))
        con.commit()
        con.close()
    except Exception:
        pass


def row_count(market: str) -> int:
    try:
        con = _conn()
        cur = con.execute("SELECT COUNT(*) FROM sepa_cache WHERE market=?", (market,))
        n = cur.fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0
