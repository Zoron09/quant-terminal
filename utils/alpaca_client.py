"""
Alpaca Markets — primary data source for US stocks.
Uses alpaca-py SDK (https://github.com/alpacahq/alpaca-py).

Free IEX feed:
  - Real-time snapshots via multi-symbol batch (1000 symbols / call, ~1s)
  - 5+ years daily OHLCV with split/dividend adjustment
  - WebSocket 1-min bar streaming

Key functions:
  get_all_us_symbols()  — full tradeable US common stock universe (~6000+), cached 24h
  get_snapshots()       — bulk real-time prices, 1000 symbols/call, cached 60s
  get_bars()            — single-symbol bars for SEPA analysis page, cached 15min
  fetch_bars_batch()    — uncached bars for screener scan loops (processes and discards)
  get_bars_bulk()       — cached batch bars for small fixed universes (≤200 symbols)
  get_stream_manager()  — WebSocket singleton for live price streaming
"""
import os
import re
import threading
import asyncio
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

ALPACA_KEY    = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET = os.getenv('ALPACA_API_SECRET', '')

_HAS_ALPACA = bool(
    ALPACA_KEY and ALPACA_SECRET
    and not ALPACA_SECRET.startswith('(')
    and ALPACA_KEY not in ('', 'your_key_here')
)

_hist_client = None


def _get_client():
    global _hist_client
    if _hist_client is None and _HAS_ALPACA:
        from alpaca.data import StockHistoricalDataClient
        _hist_client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
    return _hist_client


def _norm_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalise an Alpaca bars DataFrame to yfinance-compatible column names."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.index, pd.MultiIndex):
        lvl0 = df.index.get_level_values(0)
        if symbol not in lvl0:
            return pd.DataFrame()
        df = df.xs(symbol, level=0).copy()
    else:
        df = df.copy()
    # Strip timezone (Alpaca returns UTC-aware timestamps)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    else:
        df.index = pd.DatetimeIndex(df.index)
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume',
        'vwap': 'VWAP', 'trade_count': 'Trades',
    })
    return df.sort_index()


# ── Asset universe ─────────────────────────────────────────────────────────────

# Valid major-exchange codes returned by Alpaca TradingClient
_VALID_EXCHANGES = {
    'AssetExchange.NYSE', 'AssetExchange.NASDAQ',
}
# Symbols ending in these suffixes are warrants / rights
_WARRANT_RE = re.compile(r'(W|WS|WI|WT|WW|RT)$')


def _is_common_stock(asset) -> bool:
    """Return True if the Alpaca asset looks like a common stock (not ETF/warrant/preferred/OTC)."""
    if str(asset.exchange) not in _VALID_EXCHANGES:
        return False
    if not asset.tradable:
        return False
    sym = asset.symbol
    # Common stocks: 1-5 uppercase letters, optional one-letter class suffix via dot (e.g. BRK.B)
    if not re.match(r'^[A-Z]{1,5}$', sym):
        return False
    # Skip warrants
    if _WARRANT_RE.search(sym) and len(sym) > 3:
        return False
    # Skip anything with digits (SPAC units, ETN series, etc.)
    if any(c.isdigit() for c in sym):
        return False
    return True


@st.cache_data(ttl=86400, show_spinner=False)
def get_all_us_symbols() -> list[str]:
    """
    Fetch every active, tradeable US common stock from Alpaca's Trading API.
    Excludes: OTC stocks, ETFs (best-effort), warrants, units, preferred stock, SPACs.
    Returns a sorted list of clean ticker symbols. Cached 24 hours.

    Typical result: ~6000–8000 symbols covering NYSE, NASDAQ, ARCA, BATS, AMEX.
    """
    if not _HAS_ALPACA:
        return []
    try:
        from alpaca.trading import TradingClient
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass, AssetStatus

        tc     = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
        req    = GetAssetsRequest(
            asset_class=AssetClass.US_EQUITY,
            status=AssetStatus.ACTIVE,
        )
        assets = tc.get_all_assets(req)
        syms   = sorted({a.symbol for a in assets if _is_common_stock(a)})
        return syms
    except Exception:
        return []


# ── Snapshots: bulk real-time prices ─────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_snapshots(symbols: tuple[str, ...]) -> dict[str, dict]:
    """
    Fetch current price, change %, and today's volume for up to 1000 US symbols
    per API call (IEX real-time). Pass all symbols as a tuple; this function
    internally batches 1000 at a time.

    Returns {symbol: {price, prev_close, change_pct, open, high, low, volume, bid, ask}}
    """
    client = _get_client()
    if not client or not symbols:
        return {}

    from alpaca.data.requests import StockSnapshotRequest
    from alpaca.data.enums import DataFeed

    result   = {}
    sym_list = list(symbols)

    for i in range(0, len(sym_list), 1000):
        batch = sym_list[i:i + 1000]
        try:
            req   = StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed.IEX)
            snaps = client.get_stock_snapshot(req)
            for sym, snap in snaps.items():
                try:
                    trade = snap.latest_trade
                    daily = snap.daily_bar
                    prev  = snap.previous_daily_bar
                    quote = snap.latest_quote

                    price      = float(trade.price) if trade else (float(daily.close) if daily else None)
                    prev_close = float(prev.close)  if prev  else None
                    chg_pct    = (
                        round((price - prev_close) / prev_close * 100, 2)
                        if price and prev_close and prev_close != 0 else None
                    )
                    result[sym] = {
                        'price':      price,
                        'prev_close': prev_close,
                        'change_pct': chg_pct,
                        'open':       float(daily.open)   if daily else None,
                        'high':       float(daily.high)   if daily else None,
                        'low':        float(daily.low)    if daily else None,
                        'volume':     int(daily.volume)   if daily else None,
                        'vwap':       float(daily.vwap)   if daily and daily.vwap else None,
                        'bid':        float(quote.bid_price) if quote else None,
                        'ask':        float(quote.ask_price) if quote else None,
                    }
                except Exception:
                    pass
        except Exception:
            pass

    return result


# ── Historical bars: single symbol ───────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def get_bars(symbol: str, years: int = 3) -> pd.DataFrame:
    """
    Daily adjusted OHLCV for a single US symbol.
    Returns a yfinance-compatible DataFrame. Cached 15 min.
    """
    client = _get_client()
    if not client:
        return pd.DataFrame()

    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed, Adjustment

    try:
        start = datetime.now() - timedelta(days=365 * years + 15)
        req   = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            adjustment=Adjustment.ALL,
            feed=DataFeed.IEX,
        )
        return _norm_bars(client.get_stock_bars(req).df, symbol)
    except Exception:
        return pd.DataFrame()


# ── Historical bars: uncached batch fetcher for full-market scan ──────────────

def fetch_bars_batch(
    symbols: list[str],
    start: datetime,
) -> dict[str, pd.DataFrame]:
    """
    Fetch daily adjusted bars for a batch of US symbols.
    NOT cached — designed to be called inside a screener scan loop where
    each batch is processed immediately and results are stored in session_state.

    Uses _fetch_batch internally with binary-split retry for bad symbols.
    Returns {symbol: DataFrame} with yfinance-compatible columns.
    """
    client = _get_client()
    if not client or not symbols:
        return {}
    result = {}
    _fetch_batch(client, list(symbols), start, result)
    return result


def _fetch_batch(client, batch: list[str], start, result: dict, _depth: int = 0):
    """
    Single resilient bars request. On 400 'invalid symbol', binary-split and
    retry each half so one bad symbol can't kill the whole batch.
    Recursion caps at depth 7 (single symbol), bad symbol is silently skipped.
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import DataFeed, Adjustment

    if not batch:
        return
    try:
        req    = StockBarsRequest(
            symbol_or_symbols=batch,
            timeframe=TimeFrame.Day,
            start=start,
            adjustment=Adjustment.ALL,
            feed=DataFeed.IEX,
        )
        bars   = client.get_stock_bars(req)
        df_all = bars.df
        if df_all is None or df_all.empty:
            return

        returned_syms = (
            list(df_all.index.get_level_values(0).unique())
            if isinstance(df_all.index, pd.MultiIndex) else batch
        )
        for sym in returned_syms:
            df = _norm_bars(df_all, sym)
            if not df.empty:
                result[sym] = df

    except Exception:
        if _depth >= 7 or len(batch) <= 1:
            return
        mid = len(batch) // 2
        _fetch_batch(client, batch[:mid], start, result, _depth + 1)
        _fetch_batch(client, batch[mid:], start, result, _depth + 1)


# ── Historical bars: cached small-universe bulk fetch (≤200 symbols) ─────────

@st.cache_data(ttl=900, show_spinner=False)
def get_bars_bulk(
    symbols: tuple[str, ...],
    years: int = 2,
    batch_size: int = 100,
) -> dict[str, pd.DataFrame]:
    """
    Cached batch bars for small fixed universes (e.g. India yfinance fallback
    or quick 50-symbol test scans). For full-market scans use fetch_bars_batch().
    """
    client = _get_client()
    if not client or not symbols:
        return {}

    result   = {}
    sym_list = list(symbols)
    start    = datetime.now() - timedelta(days=365 * years + 15)

    for i in range(0, len(sym_list), batch_size):
        _fetch_batch(client, sym_list[i:i + batch_size], start, result)

    return result


# ── WebSocket streaming manager ───────────────────────────────────────────────

class StreamManager:
    """
    Thread-safe WebSocket manager for real-time 1-min bar updates.
    Runs as a daemon background thread — survives Streamlit reruns.
    Held as a module-level singleton via st.cache_resource.
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self.prices: dict[str, dict] = {}
        self.connected: bool = False
        self.error: str = ''

    def start(self, symbols: list[str]):
        if not _HAS_ALPACA:
            self.error = 'Alpaca credentials not configured.'
            return
        if self._thread and self._thread.is_alive():
            self.stop()
        self._stop_evt.clear()
        self.prices.clear()
        self.connected = False
        self.error = ''
        self._thread = threading.Thread(
            target=self._run, args=(list(symbols),),
            daemon=True, name='alpaca-ws',
        )
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=4)
        self._thread = None
        self.connected = False

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self, symbols: list[str]):
        from alpaca.data.live import StockDataStream
        from alpaca.data.enums import DataFeed

        loop   = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET, feed=DataFeed.IEX)
        mgr    = self

        async def _bar_handler(bar):
            mgr.prices[bar.symbol] = {
                'price':  float(bar.close),
                'open':   float(bar.open),
                'high':   float(bar.high),
                'low':    float(bar.low),
                'volume': int(bar.volume),
                'ts':     bar.timestamp,
            }
            if mgr._stop_evt.is_set():
                await stream.stop_ws()

        stream.subscribe_bars(_bar_handler, *symbols)
        try:
            mgr.connected = True
            stream.run()
        except Exception as e:
            mgr.error = str(e)
        finally:
            mgr.connected = False
            loop.close()


@st.cache_resource
def get_stream_manager() -> StreamManager:
    return StreamManager()
