import sys
import os
sys.path.insert(0, r"C:\Users\Meet Singh\quant-terminal")
from utils.alpaca_client import _get_client, get_snapshots, get_bars
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetExchange
from utils.sepa_engine import compute_trend_template
from datetime import datetime, timedelta
import pandas as pd
import re

def main():
    print("--- INVESTIGATING ALPACA UNIVERSE ---")
    import os
    from alpaca.trading.client import TradingClient
    from dotenv import load_dotenv
    load_dotenv()
    tc = TradingClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_API_SECRET'), paper=True)
    req = GetAssetsRequest(asset_class=AssetClass.US_EQUITY)
    assets = tc.get_all_assets(req)
    
    exchanges = {}
    symbols = []
    
    _VALID_EXCHANGES = {
        'AssetExchange.NYSE', 'AssetExchange.NASDAQ',
    }
    _WARRANT_RE = re.compile(r'(W|WS|WI|WT|WW|RT)$')
    
    for a in assets:
        ex = str(a.exchange)
        if ex not in exchanges:
            exchanges[ex] = 0
        exchanges[ex] += 1
        
        # Check standard common stock logic
        if ex in _VALID_EXCHANGES and a.tradable and '.' not in a.symbol and '-' not in a.symbol and not _WARRANT_RE.search(a.symbol):
            symbols.append(a.symbol)
            
    print("Raw Alpaca Exchanges:")
    for ex, cnt in exchanges.items():
        print(f"  {ex}: {cnt}")
        
    print(f"\nFiltered common stocks (NYSE + NASDAQ only): {len(symbols)}")
    
    test_tickers = ['ASYS', 'OCC', 'INTT', 'SODI', 'STRL']
    
    print("\n--- TEST TICKER INVESTIGATION ---")
    for t in test_tickers:
        with open("investigation_output.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{t}]\n")
            # 1. Is it in Alpaca universe?
            in_univ = False
            raw_asset = None
            for a in assets:
                if a.symbol == t:
                    in_univ = True
                    raw_asset = a
                    break
            
            if not in_univ:
                f.write(f"  NotInUniverse: {t} not found in Alpaca assets.\n")
                continue
                
            f.write(f"  Asset Details: exchange={raw_asset.exchange}, tradable={raw_asset.tradable}, status={raw_asset.status}\n")
            
            if t not in symbols:
                f.write(f"  Excluded: {t} was excluded by _is_common_stock filter! (NYSE+NASDAQ only)\n")
                
            # 2. Get snapshots (price + volume)
            snaps = get_snapshots((t,))
            snap = snaps.get(t, {})
            price = snap.get('price', 0)
            vol_today = snap.get('volume', 0)
            f.write(f"  Snapshot: price={price}, vol_today={vol_today}\n")
            
            if price < 12.0:
                f.write(f"  Fails Pre-filter: Price {price} < 12.0\n")
            
            # 3. Get historical bars
            df = get_bars(t, years=3)
            f.write(f"  Bars fetched: {len(df) if df is not None else 0} trading days\n")
            
            if df is None or len(df) < 200:
                f.write(f"  Fails History: Cannot compute SMA(200).\n")
            
            if df is None or len(df) < 100:
                continue
                
            # 4. Check ADV(30)
            vol = df['Volume'].dropna()
            avg_vol_30 = float(vol.tail(30).mean()) if len(vol) >= 30 else float(vol.mean())
            f.write(f"  ADV(30): {avg_vol_30:.0f}\n")
            if avg_vol_30 < 100000:
                f.write(f"  Fails ADV(30): {avg_vol_30:.0f} < 100,000\n")
                
            # 5. Compute SEPA
            trend = compute_trend_template(df)
            f.write(f"  Trend Pass Count: {trend.get('pass_count', 0)} / 8\n")
            for c in trend.get('criteria', []):
                if not c['result']:
                    f.write(f"    FAIL: {c['label']} -> {c['value']}\n")
                else:
                    f.write(f"    PASS: {c['label']} -> {c['value']}\n")

if __name__ == "__main__":
    main()
