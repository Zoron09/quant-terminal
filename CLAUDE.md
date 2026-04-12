# CLAUDE.md — Quant Terminal Master Specification
> Read this file at the start of EVERY session before touching any code.
> Last updated: April 12, 2026

---

## 1. Who is the user

- **Name:** Meet Singh, Delhi, India
- **Technical level:** Zero coding experience. Cannot read or write code.
- **Communication:** Short, direct. One step at a time. No long explanations unless asked.
- **Trading:** Studies Mark Minervini's SEPA methodology (books: "Trade Like a Stock Market Wizard", "Think & Trade Like a Champion")

---

## 2. What is this project

A Streamlit web app for stock research and portfolio management built around Minervini's SEPA methodology. Runs locally on Windows PC.

**Start the app:**
```bash
cd "C:\Users\Meet Singh\quant-terminal"
streamlit run app.py
```

**Open Claude Code:**
```bash
cd "C:\Users\Meet Singh\quant-terminal"
claude
```

---

## 3. Project location

```
C:\Users\Meet Singh\quant-terminal\
├── CLAUDE.md              ← This file. Always read first.
├── app.py                 ← Main entry point
├── .env                   ← API keys (NEVER commit to Git)
├── requirements.txt
├── pages/                 ← Streamlit pages (13 files)
├── utils/                 ← Core logic (11 files)
├── data/
│   ├── portfolios.json    ← Meet's actual holdings (sensitive)
│   ├── price_alerts.json
│   └── screener_cache.db  ← SQLite cache
└── styles/custom.css      ← Dark theme
```

---

## 4. API keys (.env)

```
ALPACA_API_KEY=<key>
ALPACA_API_SECRET=<secret>
FINNHUB_API_KEY=<key>
```

Never commit .env to Git.

---

## 5. Data architecture (finalized)

| Data | Primary Source | Fallback |
|------|---------------|----------|
| Financial statements (IS, BS, CF) | SEC EDGAR data.sec.gov | yfinance |
| Real-time price + OHLC | Alpaca | yfinance |
| EPS estimates + surprises | Finnhub | yfinance |
| News | Finnhub + Alpaca | — |
| Indian stocks (.NS) | yfinance only | — |
| Canadian stocks (.TO) | yfinance only | — |

### SEC EDGAR API
- Base URL: https://data.sec.gov/
- No API key required. No rate limits.
- Company facts: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
- MUST set header: User-Agent: Meet Singh singhgaganmeet09@gmail.com
- Returns XBRL financial data direct from official SEC filings

---

## 6. What is already built

### Phase 1 — Stock Research (13 features)
Company snapshot, key stats, financial statements, revenue/earnings charts, margin trends, ratio dashboard, DCF model, Piotroski F-Score, earnings calendar, analyst ratings, insider transactions, institutional holders, peer comparison.

### Phase 2 — SEPA Engine (11 features)
Trend Template (8 criteria), Weinstein Stage, RS Ranking, RS Line chart, VCP detection, earnings acceleration, Code 33 detector, volume dry-up, buy trigger zone, composite SEPA score (0-100).

### Phase 3 — News & Sentiment (5 features)
Real-time news (Finnhub + Alpaca), SEC filings feed, price alerts, Finnhub sentiment, Stocktwits.

### Phase 4 — Portfolio (9 features)
Holdings input, real-time P&L via Alpaca, portfolio optimizer, risk metrics, position sizing, backtesting, sector exposure, Canadian stock support.

### Phase 5 — Market Dashboard (6 features)
Index cards (SPX, NASDAQ, DOW, NIFTY, SENSEX, RUT), sector heatmap, market breadth, VIX, currencies/commodities, economic calendar.

---

## 7. CURRENT PRIORITY — New stock detail page

Build: pages/15_stock_detail.py

Do NOT modify existing pages. Build this as a new standalone page.

### Header
- Ticker, exchange, sector
- Company name
- Current price (large)
- Dollar change + % change (green if up, red if down)
- After hours price if available

### OHLC bar
Single row: Open | High | Low | Prev Close | Volume | Avg Volume | 52W High | 52W Low

### Price chart
- Line chart from Alpaca historical data
- Time range toggle: 1D / 1W / 1M / 3M / 6M / 1Y
- Green line if up from start of range, red if down

### Tab 1: Overview
12 metric cards (4 columns x 3 rows):
Market Cap, P/E TTM, P/E Forward, EPS TTM, Revenue TTM, Gross Margin, Net Margin, Beta, ROE, Debt/Equity, Dividend Yield, Float Shares
Plus collapsible company description.

### Tab 2: Financials
- Period toggle: Quarterly / Annual
- Chart type toggle: Bar / Line
- Mini chart above each table

Income Statement rows (ALL required — no shortcuts):
Revenue, Revenue Growth YoY%, Gross Profit, Gross Margin%, Operating Income, Operating Margin%, EBITDA, Interest Expense, Net Income, Net Margin%, EPS Diluted, EPS Growth YoY%

Balance Sheet rows:
Cash & Equivalents, Total Current Assets, Total Assets, Total Current Liabilities, Long-term Debt, Total Liabilities, Total Equity

Cash Flow rows:
Operating Cash Flow, Capital Expenditure, Free Cash Flow, Share Buybacks, Dividends Paid

Data source: SEC EDGAR primary, yfinance fallback.
Color code: green for positive growth, red for negative.

### Tab 3: Earnings
4 insight cards: Last Reported Date, Next Earnings Estimate, EPS Beat Rate (last 8Q), Revenue Beat Rate (last 8Q)

Surprise table columns:
Quarter | EPS Est | EPS Actual | EPS Surprise% | Rev Est | Rev Actual | Rev Surprise%

Beats = green, misses = red.
Data source: Finnhub.

### Tab 4: Code 33
THIS IS THE MOST IMPORTANT TAB. Build with extreme accuracy.

Status badge: Active (green) / At Risk (yellow) / Broken (red)

STRICT MINERVINI CODE 33 RULES:
- Requires YoY EPS growth RATE accelerating quarter over quarter (delta > 0)
- Same for Revenue growth rate (YoY)
- Same for Net Profit Margin (expanding each quarter)
- ALL THREE must accelerate simultaneously
- Must hold for 3 consecutive quarters

Delta display:
- Show growth rate for each of last 3 quarters
- Show delta (pp change) between quarters
- Green delta = accelerating
- Yellow delta = positive but shrinking
- Red delta = negative

Status rules:
- GREEN = all 3 metrics have positive AND increasing deltas
- YELLOW = all 3 still positive but at least one delta is shrinking
- RED = any delta turns negative (even if growth rate is still high number)

CRITICAL: High growth but decelerating = RED not yellow.
Example: EPS growth 80% -> 65% -> 28% = RED (Code 33 broken).
This is the Dell Computer trap Minervini explicitly warns about.

Show note: "Per Minervini, a shrinking delta signals institutional selling even at high growth rates. Dell peaked when EPS growth decelerated from 80% to 28%."

### Tab 5: News
Finnhub + Alpaca news. Show source, time ago, headline. Auto-refresh every 5 minutes.

---

## 8. SEPA rules (exact implementation)

### Trend Template (7-8 of 8 to qualify)
1. Price > 150-day MA
2. Price > 200-day MA
3. 150-day MA > 200-day MA
4. 200-day MA trending up >= 1 month
5. 50-day MA > 150-day MA AND 200-day MA
6. Price > 50-day MA
7. Price >= 30% above 52-week low (NOT 25%)
8. Price within 25% of 52-week high

### SEPA score caps
- Earnings not fetched: max 80
- Earnings fetched + accelerating: up to 100
- Earnings fetched + NOT accelerating: capped at 55

---

## 9. Known bugs fixed (do not reintroduce)

| Bug | Fix |
|-----|-----|
| BRK-B crash | Use BRK.B format, binary-split retry on 400 errors |
| SEPA score too high | Cap at 55 when earnings not accelerating |
| VCP false positives | Strict left-to-right decreasing validation |
| Insider missing buy/sell | Map P=Purchase, S=Sale, A=Award, M=Exercise |
| VISA showing N/A | Ticker map: VISA->V, FACEBOOK->META |
| NaN screener crash | NaN-safe helpers on all numeric columns |
| Screener only 50 stocks | Full Alpaca asset list (11,000+) |

---

## 10. Portfolio positions

AMD, AMZN, IREN, MELI, MSFT, NFLX, NVDA, QQQ, SOFI, V, XDIV.TO
Brokers: Questrade, Moomoo, Wealthsimple

---

## 11. Session rules

1. Always start: Read CLAUDE.md
2. Batch all changes into one prompt
3. End every prompt: Compile check all files. Restart streamlit.
4. Select "Yes, and always allow" for pip and python
5. Sonnet for routine work. Opus only for complex features.
6. After every session: git add . && git commit -m "description" && git push
7. Always end every prompt with: git add . && git commit -m "describe what changed" && git push
