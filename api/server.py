from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
import io
import sys
import os
import yfinance as yf
from functools import lru_cache
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.code33_engine import get_code33_data, CACHE_VERSION

TICKER_CACHE = {}
CACHE_TTL = 300  # 5 minutes

def evict_cache():
    now = time.time()
    expired = [k for k, v in list(TICKER_CACHE.items()) if now - v[1] > CACHE_TTL]
    for k in expired: TICKER_CACHE.pop(k, None)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve HTML files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def root():
    return FileResponse("frontend/screener.html")

@app.get("/overview")
async def overview():
    return FileResponse("frontend/overview.html")

@app.get("/portfolio")
async def portfolio():
    return FileResponse("frontend/portfolio.html")

@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    contents = await file.read()
    df = pd.read_csv(io.BytesIO(contents))
    
    sector_map = {}
    mcap_map = {}
    
    if 'Symbol' in df.columns and 'Sector' in df.columns:
        sector_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Sector'].fillna('Unknown')
        ))
    
    company_map = {}
    if 'Symbol' in df.columns and 'Description' in df.columns:
        company_map = dict(zip(
            df['Symbol'].str.upper(),
            df['Description'].fillna('')
        ))

    if 'Symbol' in df.columns and 'Market capitalization' in df.columns:
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                if v >= 1e6:  return f"${v/1e6:.1f}M"
                return f"${v:,.0f}"
            except: return "N/A"
        mcap_map = {
            str(row['Symbol']).upper(): fmt_mcap(row['Market capitalization'])
            for _, row in df.iterrows()
        }

    import time
    start = time.time()
    
    tickers = df['Symbol'].str.upper().tolist() \
        if 'Symbol' in df.columns else []

    print(f"[SCAN] START - file received: {file.filename}")
    print(f"[SCAN] tickers count: {len(tickers)}")
    print(f"[SCAN] first 5 tickers: {tickers[:5]}")

    import concurrent.futures

    winners = []
    insufficient = 0
    crashes = 0
    count_green = 0
    count_yellow = 0
    count_red = 0
    total = len(tickers)

    def safe3(lst):
        if not lst: return [0, 0, 0]
        lst = [x for x in lst if x is not None]
        if len(lst) < 3:
            lst = ([0] * (3 - len(lst))) + lst
        return [round(x, 1) for x in lst[-3:]]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_ticker = {executor.submit(get_code33_data, t, CACHE_VERSION): t for t in tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                data = future.result(timeout=15)
                if not data:
                    insufficient += 1
                    continue
                
                status = data.get('status', 'insufficient')
                if status == 'green': count_green += 1
                elif status == 'yellow': count_yellow += 1
                elif status == 'red': count_red += 1
                elif status == 'insufficient': insufficient += 1

                if status not in ('green', 'yellow'):
                    continue

                winners.append({
                    'ticker':  ticker,
                    'company': company_map.get(ticker, '') or data.get('company_name', ticker),
                    'sector':  sector_map.get(ticker, 'Unknown'),
                    'mcap':    mcap_map.get(ticker, 'N/A'),
                    'eps':     safe3(data.get('eps_yoy', [])),
                    'rev':     safe3(data.get('rev_yoy', [])),
                    'margin':  safe3(data.get('npm', [])),
                    'status':  status,
                })
            except concurrent.futures.TimeoutError:
                print(f"[SCAN ERROR] {ticker}: Timeout")
                insufficient += 1
                crashes += 1
            except Exception as e:
                print(f"[SCAN ERROR] {ticker}: {e}")
                insufficient += 1
                crashes += 1

    print(f"[SCAN] COMPLETE - green: {count_green}, yellow: {count_yellow}, red: {count_red}, insufficient: {insufficient}, crashes: {crashes}")
    print(f"[SCAN] first winner: {winners[0] if winners else 'none'}")
    print(f"[SCAN] duration: {time.time()-start:.1f}s")
    return JSONResponse({
        'winners': winners,
        'meta': {
            'total': total,
            'passed': len(winners),
            'insufficient': insufficient,
        }
    })

@app.get("/api/ticker/{ticker}")
async def ticker_data(ticker: str):
    t = ticker.upper()
    now = time.time()
    evict_cache()
    
    if t in TICKER_CACHE:
        cached, ts = TICKER_CACHE[t]
        if now - ts < CACHE_TTL:
            return JSONResponse(cached)
    
    try:
        data = get_code33_data(t, CACHE_VERSION)
        if not data:
            return JSONResponse({'error': 'No data'}, 
                                status_code=404)
        
        data['status'] = data.get('status', 'insufficient')
        

        tk = yf.Ticker(t)
        info = tk.fast_info
        full_info = tk.info or {}
        data['price'] = getattr(info, 'last_price', 0)
        data['company_name'] = full_info.get(
            'shortName', t)
            
        data['change'] = getattr(info, 'last_price', 0) - \
          getattr(info, 'regular_market_previous_close', 
          getattr(info, 'previous_close', 0))
          
        data['change_pct'] = (data['change'] / 
          getattr(info, 'regular_market_previous_close',
          getattr(info, 'previous_close', 1))) * 100
        
        mc = getattr(info, 'market_cap', None)
        if mc is None:
            mc = full_info.get('marketCap', 0)
        def fmt_mcap(v):
            try:
                v = float(v)
                if v >= 1e12: return f"{v/1e12:.1f}T"
                if v >= 1e9:  return f"{v/1e9:.1f}B"
                if v >= 1e6:  return f"{v/1e6:.1f}M"
                return f"{v:,.0f}"
            except: return "N/A"
        data['market_cap_fmt'] = fmt_mcap(mc)
        
        data['pe_ratio'] = full_info.get(
            'trailingPE', 'N/A')

        data['week52_high'] = getattr(
            info, 'year_high', 0)
        data['week52_low'] = getattr(
            info, 'year_low', 0)
        data['avg_volume'] = getattr(
            info, 'three_month_average_volume', 0)
        
        import logging
        logging.warning(f"DATA KEYS: {list(data.keys())}")
        
        TICKER_CACHE[t] = (data, now)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/chart/{ticker}")
async def chart_data(ticker: str, period: str = "3mo"):
    t = ticker.upper()
    cache_key = f"chart_{t}_{period}"
    now = time.time()
    evict_cache()
    
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 300:
            return JSONResponse(cached)
    
    try:
        hist = yf.Ticker(t).history(period=period)
        if hist.empty:
            return JSONResponse({'error': 'No data'}, 
                                status_code=404)
        
        prices = [
            {
                'date': str(idx.date()),
                'close': round(float(row['Close']), 2)
            }
            for idx, row in hist.iterrows()
        ]
        
        result = {'ticker': t, 'period': period, 
                  'prices': prices}
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)}, 
                            status_code=500)

@app.get("/api/financials/{ticker}")
async def financials(ticker: str):
    import numpy as np
    t = ticker.upper()
    cache_key = f"fin_{t}"
    now = time.time()
    evict_cache()
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 600:
            return JSONResponse(cached)
    try:
        tk = yf.Ticker(t)
        def df_to_dict(df):
            if df is None or df.empty:
                return {}
            df = df.copy()
            result = {}
            for idx in df.index:
                row = {}
                for col in df.columns:
                    val = df.loc[idx, col]
                    if hasattr(val, 'item'):
                        val = val.item()
                    if val is None or (
                        isinstance(val, float) and 
                        np.isnan(val)):
                        val = None
                    row[str(col.date() if hasattr(
                        col, 'date') else col)] = val
                result[str(idx)] = row
            return result
        
        def fmt_val(v):
            if v is None: return None
            try:
                v = float(v)
                if abs(v) >= 1e9:
                    return f"{v/1e9:.2f}B"
                if abs(v) >= 1e6:
                    return f"{v/1e6:.0f}M"
                return f"{v:.2f}"
            except: return None
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            f_inc = executor.submit(lambda: tk.quarterly_income_stmt)
            f_bal = executor.submit(lambda: tk.quarterly_balance_sheet)
            f_cf  = executor.submit(lambda: tk.quarterly_cashflow)
            f_info = executor.submit(lambda: tk.info)
            f_cal = executor.submit(lambda: tk.calendar)
            f_ann = executor.submit(lambda: tk.income_stmt)
            
            inc = f_inc.result()
            bal = f_bal.result()
            cf  = f_cf.result()
            info = f_info.result() or {}
            cal_data = f_cal.result()
            ann = f_ann.result()
        
        earnings_list = []
        if inc is not None and not inc.empty:
            dates = sorted(inc.columns, reverse=True)[:12]
            for d in dates:
                col = inc[d]
                rev = None
                for r_key in ['TotalRevenue', 'Total Revenue', 'OperatingRevenue']:
                    if r_key in col.index and not np.isnan(col[r_key]):
                        rev = col[r_key].item() if hasattr(col[r_key], 'item') else col[r_key]
                        break
                eps = None
                for e_key in ['DilutedEPS', 'Diluted EPS', 'BasicEPS', 'Basic EPS']:
                    if e_key in col.index and not np.isnan(col[e_key]):
                        eps = col[e_key].item() if hasattr(col[e_key], 'item') else col[e_key]
                        break
                if eps is None:
                    ni = None
                    for ni_key in ['NetIncomeCommonStockholders']:
                        if ni_key in col.index and not np.isnan(col[ni_key]):
                            ni = col[ni_key].item() if hasattr(col[ni_key], 'item') else col[ni_key]
                            break
                    shares = None
                    for s_key in ['DilutedAverageShares', 'BasicAverageShares']:
                        if s_key in col.index and not np.isnan(col[s_key]):
                            shares = col[s_key].item() if hasattr(col[s_key], 'item') else col[s_key]
                            break
                    if ni is not None and shares is not None and shares > 0:
                        eps = ni / shares
                if eps is None and rev is None:
                    continue
                earnings_list.append({
                    'date': str(d.date() if hasattr(d, 'date') else d).split(' ')[0],
                    'revenue': rev,
                    'eps': eps
                })
        
        for i in range(len(earnings_list)):
            earnings_list[i]['eps_yoy'] = None
            curr = earnings_list[i]['eps']
            if curr is None: continue
            if i + 4 < len(earnings_list):
                prev = earnings_list[i+4]['eps']
                if prev is not None and prev != 0:
                    earnings_list[i]['eps_yoy'] = ((curr - prev) / abs(prev)) * 100
            else:
                curr_date = earnings_list[i]['date']
                curr_year = int(curr_date.split('-')[0])
                prior_year = curr_year - 1
                prev_eps_annual = None
                if ann is not None and not ann.empty:
                    for d_ann in ann.columns:
                        try:
                            dy = d_ann.year
                        except:
                            dy = int(str(d_ann).split('-')[0])
                        if dy == prior_year:
                            col_ann = ann[d_ann]
                            for e_key in ['DilutedEPS', 'Diluted EPS', 'BasicEPS', 'Basic EPS']:
                                if e_key in col_ann.index and not np.isnan(col_ann[e_key]):
                                    prev_eps_annual = col_ann[e_key].item() if hasattr(col_ann[e_key], 'item') else col_ann[e_key]
                                    break
                            break
                if prev_eps_annual is not None and prev_eps_annual != 0:
                    prev_q = prev_eps_annual / 4
                    earnings_list[i]['eps_yoy'] = ((curr - prev_q) / abs(prev_q)) * 100
        
        earnings_list = earnings_list[:8]

        next_earnings = None
        try:
            cal = cal_data
            if isinstance(cal, dict) and 'Earnings Date' in cal:
                ed = cal['Earnings Date']
                if isinstance(ed, list) and len(ed) > 0:
                    next_earnings = str(ed[0])
            elif hasattr(cal, 'iloc') and 'Earnings Date' in cal.index:
                val = cal.loc['Earnings Date']
                if hasattr(val, 'iloc'): val = val.iloc[0]
                next_earnings = str(val.date() if hasattr(val, 'date') else val).split(' ')[0]
        except: pass
        
        result = {
            'balance_sheet': df_to_dict(bal),
            'cash_flow': df_to_dict(cf),
            'valuation': {
                'P/E ratio': info.get('trailingPE'),
                'Forward P/E': info.get('forwardPE'),
                'P/S ratio': info.get('priceToSalesTrailing12Months'),
                'P/B ratio': info.get('priceToBook'),
                'EV/EBITDA': info.get('enterpriseToEbitda'),
                'EV/Revenue': info.get('enterpriseToRevenue'),
                'Debt/Equity': info.get('debtToEquity'),
                'ROE': info.get('returnOnEquity'),
                'ROA': info.get('returnOnAssets'),
                'Profit margin': info.get('profitMargins'),
            },
            'earnings': earnings_list,
            'next_earnings': next_earnings
        }
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'error': str(e)})

@app.get("/api/news/{ticker}")
async def news(ticker: str):
    import feedparser
    t = ticker.upper()
    cache_key = f"news_{t}"
    now = time.time()
    evict_cache()
    
    if cache_key in TICKER_CACHE:
        cached, ts = TICKER_CACHE[cache_key]
        if now - ts < 300:
            return JSONResponse(cached)
    
    try:
        url = (f"https://feeds.finance.yahoo.com"
               f"/rss/2.0/headline?s={t}"
               f"&region=US&lang=en-US")
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:9]:
            import calendar
            ts = int(calendar.timegm(
                entry.published_parsed
            )) if hasattr(entry, 'published_parsed') \
              and entry.published_parsed else \
              int(time.time()) - 3600
            
            items.append({
                'title': entry.get('title', ''),
                'source': entry.get('source', {})
                    .get('value', 'Yahoo Finance') 
                    if hasattr(entry, 'source') 
                    else 'Yahoo Finance',
                'url': entry.get('link', ''),
                'time': ts
            })
        
        result = {'news': items}
        TICKER_CACHE[cache_key] = (result, now)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({'news': [], 
                            'error': str(e)})

@app.get("/api/ownership/{ticker}")
async def ownership(ticker: str):
    from datetime import datetime
    def fmt_date(d):
        try:
            if isinstance(d, str):
                dt = datetime.strptime(d.split(' ')[0], '%Y-%m-%d')
            else:
                dt = pd.Timestamp(d).to_pydatetime()
            return dt.strftime('%b %d')
        except:
            return str(d)

    try:
        t = yf.Ticker(ticker.upper())
        holders = t.institutional_holders
        insiders = t.insider_transactions
        
        inst_list = []
        if holders is not None and not holders.empty:
            for _, row in holders.head(5).iterrows():
                pct = float(row.get('pctHeld', 
                      row.get('% Out', 0))) * 100
                inst_list.append({
                    'name': str(row.get('Holder', 
                            row.get('Name', ''))),
                    'pct': round(pct, 1)
                })
        
        insider_list = []
        if insiders is not None and not insiders.empty:
            for _, row in insiders.head(3).iterrows():
                val = float(row.get('Value', 0))
                insider_list.append({
                    'name': str(row.get('Insider', '')),
                    'role': str(row.get('Relationship', '')),
                    'date': fmt_date(row.get('Start Date', '')),
                    'value': val,
                    'type': 'BUY' if val > 0 else 'SELL'
                })
        
        return JSONResponse({
            'institutional': inst_list,
            'insiders': insider_list
        })
    except Exception as e:
        return JSONResponse({
            'institutional': [],
            'insiders': []
        })

@app.get("/api/peers/{ticker}")
async def peers(ticker: str):
    from utils.code33_engine import get_code33_data, CACHE_VERSION
    try:
        info = yf.Ticker(ticker.upper()).info
        # Get peers from recommendationKey or sector peers
        # Use analyst recommendations to find peer tickers
        recs = yf.Ticker(ticker.upper()).recommendations
        # Get sector and find similar companies
        sector = info.get('sector', '')
        
        # Hardcode peers per sector as fallback
        SECTOR_PEERS = {
            'Technology': ['NVDA','MSFT','AAPL','GOOGL','META'],
            'Health Technology': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Healthcare': ['LLY','NVO','ABBV','MRK','AMGN'],
            'Consumer Cyclical': ['AMZN','TSLA','HD','MCD','NKE'],
            'Financial Services': ['JPM','BAC','GS','MS','V'],
            'Energy': ['XOM','CVX','COP','SLB','EOG'],
            'Industrials': ['CAT','DE','HON','UPS','LMT'],
            'Communication Services': ['META','GOOGL','NFLX','DIS','CMCSA'],
        }
        
        peer_tickers = SECTOR_PEERS.get(sector, [])
        # Remove self
        peer_tickers = [p for p in peer_tickers 
                       if p != ticker.upper()][:4]
        
        peers_data = []
        for p in peer_tickers:
            try:
                d = get_code33_data(p, CACHE_VERSION)
                if not d:
                    continue
                last_eps = next((x for x in reversed(
                    d.get('eps_yoy', []) or []) 
                    if x is not None), None)
                last_rev = next((x for x in reversed(
                    d.get('rev_yoy', []) or []) 
                    if x is not None), None)
                last_npm = next((x for x in reversed(
                    d.get('npm', []) or []) 
                    if x is not None), None)
                peers_data.append({
                    'ticker': p,
                    'eps_yoy': round(last_eps, 1) 
                               if last_eps is not None else None,
                    'rev_yoy': round(last_rev, 1) 
                               if last_rev is not None else None,
                    'npm': round(last_npm, 1) 
                           if last_npm is not None else None,
                    'status': d.get('status', '')
                })
            except:
                continue
        
        return JSONResponse({
            'ticker': ticker.upper(),
            'peers': peers_data
        })
    except Exception as e:
        return JSONResponse({
            'ticker': ticker.upper(),
            'peers': [],
            'error': str(e)
        })


