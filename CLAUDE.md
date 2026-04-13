# CLAUDE.md — Quant Terminal Master Specification
> Read this file at the start of EVERY session before touching any code.
> Last updated: April 13, 2026

---

## 1. Who is the user

- **Name:** Meet Singh, Delhi, India (relocating to NSW Australia June 2026)
- **Technical level:** Zero coding experience. Cannot read or write code.
- **Communication:** Short, direct. One step at a time. No long explanations unless asked.
- **Trading:** Studies Mark Minervini's SEPA methodology (books: "Trade Like a Stock Market Wizard", "Think & Trade Like a Champion")

---

## 2. What is this project

A Bloomberg-style Streamlit stock research terminal built around Minervini's SEPA methodology. Runs locally on Windows PC at localhost:8501.

**Start the app:**
```bash
cd "C:\Users\Meet Singh\quant-terminal"
streamlit run app.py
```

---

## 3. Project location

```
C:\Users\Meet Singh\quant-terminal\
├── CLAUDE.md              ← This file. Always read first.
├── app.py                 ← Main entry point (Overview page)
├── .env                   ← API keys (NEVER commit to Git)
├── requirements.txt
├── pages/
│   ├── 2_Financials.py
│   ├── 3_Growth_and_Margins.py
│   ├── 4_Valuation.py
│   ├── 5_Earnings.py
│   ├── 6_Analyst_Ratings.py
│   ├── 7_Ownership.py
│   ├── 8_Peer_Comparison.py
│   ├── 9_SEPA_Analysis.py
│   ├── 10_Screener.py
│   ├── 11_News_Sentiment.py
│   ├── 12_Portfolio.py
│   ├── 13_Market_Dashboard.py
│   └── 15_stock_detail.py
├── utils/
│   ├── alpaca_client.py   ← Alpaca data + WebSocket streaming
│   ├── data_fetcher.py    ← Routing: Alpaca primary, yfinance fallback
│   ├── sepa_engine.py     ← All SEPA calculations
│   ├── screener_db.py     ← SQLite cache for screener
│   ├── finnhub_client.py  ← News, analyst, earnings data
│   ├── sec_edgar.py       ← SEC filings
│   ├── portfolio_engine.py
│   ├── dcf_model.py
│   ├── piotroski.py
│   ├── formatters.py
│   └── sidebar.py
├── data/
│   ├── portfolios.json    ← Meet's actual holdings
│   ├── sp500_tickers.json
│   ├── nifty500_tickers.json
│   ├── price_alerts.json
│   └── screener_cache.db  ← SQLite SEPA cache
└── styles/custom.css      ← Bloomberg dark theme
```

---

## 4. API keys (.env)

```
ALPACA_API_KEY=<key>
ALPACA_API_SECRET=<secret>
FINNHUB_API_KEY=<key>
```

NEVER commit .env to Git. It is in .gitignore.

---

## 5. Data architecture

| Data | Primary | Fallback |
|------|---------|----------|
| US price history + real-time | Alpaca IEX | yfinance |
| Financial statements | yfinance | SEC EDGAR |
| News | Finnhub + Alpaca | — |
| Analyst ratings + earnings surprises | Finnhub | yfinance |
| Insider transactions | Finnhub | yfinance |
| Indian stocks (.NS/.BO) | yfinance only | — |
| Canadian stocks (.TO) | yfinance only | — |
| Indices (^GSPC, ^NSEI) | yfinance only | — |

---

## 6. Design rules (NEVER change these)

- Background: #0E1117 (black)
- Accent: #00FF41 (neon green)
- Positive values: #00FF41
- Negative values: #FF4444
- Warnings: #FFD700
- Font: Courier New monospace for all numbers
- Every number right-aligned, every label left-aligned
- Dark theme only — never light mode

---

## 7. What is already built

### Phase 1 — Stock Research (app.py + pages 2-8)
- app.py: Overview — top bar, company snapshot, key statistics, dividends
- Page 2: Financial statements (IS, BS, CF) — annual/quarterly toggle
- Page 3: Growth & margins charts — revenue, EPS, margin trends
- Page 4: Valuation — ratio dashboard, DCF model, Piotroski F-Score
- Page 5: Earnings — calendar, history table, surprise chart, estimates
- Page 6: Analyst ratings — consensus, price targets, upgrades/downgrades
- Page 7: Ownership — insider transactions (Finnhub+yfinance), institutional holders
- Page 8: Peer comparison — sector peers, color-coded metrics table

### Phase 2 — SEPA Engine (pages 9-10)
- Page 9: SEPA Analysis — full trend template, price chart with MAs, Weinstein stage, RS ranking, VCP detection, earnings acceleration, Code 33 detector, volume dry-up, buy trigger zone
- Page 10: Screener — full US market scan via Alpaca (~6000-11000 stocks), SQLite cache, instant results, 6 quick scan presets, live WebSocket feed

### Phase 3 — News & Sentiment (page 11)
- Finnhub + Alpaca news feed, SEC filings, price alerts

### Phase 4 — Portfolio (page 12)
- Holdings: AMD, AMZN, IREN, MELI, MSFT, NFLX, NVDA, QQQ, SOFI, V, XDIV.TO
- Real-time P&L via Alpaca, optimizer, risk metrics, backtesting, position sizing

### Phase 5 — Market Dashboard (page 13)
- Index cards, sector heatmap, market breadth, VIX, currencies/commodities

---

## 8. SEPA engine — exact rules

### Trend Template (7+ of 8 = SEPA Qualified)
1. Price > 150-day MA
2. Price > 200-day MA
3. 150-day MA > 200-day MA
4. 200-day MA trending up >= 1 month
5. 50-day MA > 150-day MA AND 200-day MA
6. Price > 50-day MA
7. Price >= 30% above 52-week low (Minervini's rule — NOT 25%)
8. Price within 25% of 52-week high

### SEPA composite score weights
- Trend Template: 30%
- RS Rank: 20%
- Earnings Acceleration: 20%
- VCP: 15%
- Volume/Stage: 15%

### Score caps
- Earnings not fetched (fast scan): max 80 naturally
- Earnings fetched + accelerating: up to 100
- Earnings fetched + NOT accelerating: hard cap at 55

### Weinstein Stage
- Stage 2 (Advancing): price above rising MA150 → ideal
- Stage 1 (Basing): price around flat MA150
- Stage 3 (Topping): price above falling MA150 → caution
- Stage 4 (Declining): price below falling MA150 → avoid

### VCP (Volatility Contraction Pattern)
- Valid VCP: ALL contractions strictly decreasing left to right
- Invalid VCP: has 3+ contractions but not all progressive
- Uses 10-day rolling windows over 60-day lookback

### Code 33 (most important signal)
Requires ALL THREE simultaneously for 3 consecutive quarters:
- EPS YoY growth RATE accelerating (delta > 0)
- Revenue YoY growth RATE accelerating (delta > 0)
- Net Profit Margin expanding (delta > 0)

Status rules:
- GREEN = all 3 metrics have positive AND increasing deltas
- YELLOW = all 3 still positive but at least one delta shrinking
- RED = any delta turns negative

CRITICAL: High growth but decelerating = RED (the Dell Computer trap).
Example: EPS growth 80% → 65% → 28% = RED even though growth is positive.

---

## 9. Screener architecture

- Phase 0: Load ~6000-11000 US symbols from Alpaca Trading API
- Phase 1: Bulk real-time snapshots (1000 symbols/call, ~1s each)
- Phase 2+3: Batch OHLCV bars (500/batch) + SEPA compute
- Auto-enrich top 200 by SEPA score with yfinance earnings data
- All results stored in SQLite (screener_cache.db)
- Subsequent loads instant from SQLite (<3 sec)
- India fallback: yfinance, Nifty 500 universe

---

## 10. Known bugs — DO NOT reintroduce

| Bug | Fix applied |
|-----|-------------|
| BRK-B crash | Use BRK.B format, binary-split retry on 400 errors |
| SEPA score too high | Cap at 55 when earnings not accelerating |
| VCP false positives | Strict left-to-right decreasing validation |
| Insider missing buy/sell | Map P=Purchase S=Sale A=Award M=Exercise F=Tax |
| NaN screener crash | NaN-safe helpers (_safe_float, _safe_int, _safe_bool) on all numeric columns |
| RS timezone mismatch | Strip tz from both Alpaca and yfinance before index intersection |
| Screener only 50 stocks | Full Alpaca asset list via TradingClient |

---

## 11. Session rules for AI agent

1. Always read CLAUDE.md first before any code changes
2. Batch all related changes into single operations
3. After every change: verify no syntax errors
4. NEVER modify .env
5. NEVER break existing working pages
6. Always end every session with:
```
   git add .
   git commit -m "describe what changed"
   git push
```
7. Use PowerShell `;` instead of `&&` for chaining commands on Windows
