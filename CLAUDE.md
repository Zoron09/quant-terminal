# CLAUDE.md — Quant Terminal Master Specification
> Read this file at the start of EVERY session before touching any code.

---

## 1. Who is the user

- **Name:** Meet Singh, Delhi, India
- **Technical level:** Zero coding experience. Cannot read or write code.
- **Communication:** Short, direct instructions only. One step at a time. No long explanations unless asked.
- **Trading:** Studies Mark Minervini's SEPA methodology.

---

## 2. What is this project

A Streamlit web app for stock research and portfolio management built around Minervini's SEPA methodology. Runs locally on Windows PC.

**Start the app:**
```bash
cd "C:\Users\Meet Singh\quant-terminal"
streamlit run app.py
# Open http://localhost:8501
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

Never commit `.env` to Git.

---

## 5. Data sources (priority order)

| Data | Primary | Fallback |
|------|---------|---------|
| US stock prices | Alpaca (real-time IEX) | yfinance |
| Indian stocks (.NS) | yfinance only | — |
| Canadian stocks (.TO) | yfinance only | — |
| News | Finnhub → Alpaca | — |
| Fundamentals | yfinance | Finnhub |
| Analyst ratings | Finnhub | yfinance |
| Insider data | Finnhub + SEC EDGAR | — |

**Rate limits:** Alpaca = 10,000 calls/min. Finnhub = 60 calls/min.

---

## 6. What is built (phases complete)

### Phase 1 — Stock Research (13 features)
- Company snapshot, key stats (24 metrics), financial statements (5yr annual + 8Q quarterly)
- Revenue/earnings charts, margin trends, ratio dashboard
- DCF model, Piotroski F-Score, earnings calendar
- Analyst ratings, insider transactions, institutional holders, peer comparison

### Phase 2 — SEPA Engine (11 features)
- Minervini Trend Template (8 criteria, pass/fail + proximity %)
- Weinstein Stage (1-4), RS Ranking (6M + 12M), RS Line chart
- VCP detection with progressive contraction validation
- Earnings acceleration, Code 33 detector
- Volume dry-up, buy trigger zone, composite SEPA score (0-100)

### Phase 3 — News & Sentiment (5 features)
- Real-time news (Finnhub + Alpaca), SEC filings feed
- Price alerts, Finnhub sentiment gauge, Stocktwits integration

### Phase 4 — Portfolio (9 features)
- Holdings input with ticker validation, real-time P&L via Alpaca
- Portfolio optimizer (Max Sharpe / Min Volatility), risk metrics
- Position sizing (10% stop-loss), backtesting, sector exposure
- Canadian stock support (.TO with CAD→USD conversion)

### Phase 5 — Market Dashboard (6 features)
- Index cards (SPX, NASDAQ, DOW, NIFTY, SENSEX, RUT) with sparklines
- Sector heatmap, market breadth, VIX gauge, currencies/commodities, economic calendar

---

## 7. What is NOT built yet

- **Phase 6 — Options:** chain, IV chart, P/L calculator, Greeks
- **AI Analysis tab:** auto-generated research from prompt guide PDF
- **Short small cap squeeze strategy:** short interest, float, squeeze indicators
- **Automated trading bot:** Alpaca paper trading execution
- **UI redesign:** CSS overhaul or React/Next.js rebuild

---

## 8. SEPA rules (Minervini — exact implementation)

### Trend Template (must pass 7-8 of 8)
1. Price > 150-day MA
2. Price > 200-day MA
3. 150-day MA > 200-day MA
4. 200-day MA trending up ≥ 1 month
5. 50-day MA > 150-day MA AND 200-day MA
6. Price > 50-day MA
7. Price ≥ **30%** above 52-week low (not 25% — Minervini's actual rule)
8. Price within 25% of 52-week high

### SEPA Composite Score weights
| Component | Weight |
|-----------|--------|
| Trend Template | 30% |
| RS Ranking | 20% |
| Earnings Acceleration | 20% |
| VCP Pattern | 15% |
| Volume/Stage | 15% |

### Scoring caps
- Earnings not yet fetched → max 80 (Grade B), status = "Pending"
- Earnings fetched + accelerating → up to 100
- Earnings fetched + NOT accelerating → **capped at 55 (Grade C)**

### Code 33
Three consecutive quarters where EPS growth rate + revenue growth rate + profit margin are ALL accelerating simultaneously. Shows green badge when active.

### Other rules
- **No P/E filter** — Minervini ignores P/E. Superperformance stocks have high P/E.
- **10% stop loss** is non-negotiable
- Buy only in **Stage 2** (Weinstein)
- VCP contractions must be progressively smaller left to right

---

## 9. Portfolio holdings (Meet's actual positions)

AMD, AMZN, IREN, MELI, MSFT, NFLX, NVDA, QQQ, SOFI, V (entered as VISA → corrected to V), XDIV.TO

Brokers: Questrade, Moomoo, Wealthsimple (Canadian)

---

## 10. Known bugs fixed (do not reintroduce)

| Bug | Fix |
|-----|-----|
| BRK-B crash on Alpaca | Use BRK.B format, binary-split retry on 400 errors |
| SEPA score too high with no earnings | Cap at 55 when not accelerating |
| VCP false positives | Strict left-to-right decreasing contraction validation |
| Insider buy/sell missing | Map P=Purchase, S=Sale, A=Award, M=Exercise |
| VISA portfolio showing N/A | Ticker correction map (VISA→V, FACEBOOK→META) |
| NaN crash in screener | NaN-safe int/float helpers on all numeric columns |
| Screener scanning only 50 stocks | Full Alpaca asset list (11,000+) |

---

## 11. Screener architecture

**Phase 0:** Alpaca `/v2/assets` → all active US common stocks (~11,000). Cached 24hrs.
**Phase 1:** Batch snapshots (1,000/call) → filter price ≥ $5, volume ≥ 100k → ~1,000 stocks
**Phase 2:** 2yr daily bars in batches of 100 → calculate MAs, Stage, Trend Template, RS, VCP → store in SQLite
**Phase 3:** Auto-enrich top 200 by technical score with yfinance earnings → Code 33, final SEPA score → SQLite

First run: 2-3 minutes. Subsequent runs: <3 seconds via SQLite cache.

---

## 12. Claude Code session rules

1. **Always start:** `Read CLAUDE.md`
2. **Batch changes** into one prompt — never send one feature at a time
3. **End every prompt with:** `Compile check all files. Restart streamlit.`
4. **Select "Yes, and always allow"** for pip and python commands
5. **Use Sonnet** for routine fixes. Only switch to Opus for complex new features.
6. **Monitor quota** — heavy sessions burn 75%+ of weekly limit

---

## 13. Git workflow (once GitHub is set up)

```bash
# Before every session
git add .
git commit -m "Working state before changes"

# After session
git add .
git commit -m "Describe what changed"

# If something breaks
git log --oneline
git checkout <commit-hash>
```

---

## 14. Performance notes

- 8GB RAM — avoid running screener with many browser tabs open
- SQLite is single-writer — don't run two scans simultaneously
- yfinance can rate-limit during enrichment of 200 stocks (3-5 min normal)

---

## 15. Next priorities (in order)

1. Set up GitHub repo and push all code
2. Build AI Analysis tab (from prompt guide PDF)
3. Short small cap squeeze screener
4. UI CSS overhaul
5. Options tab (Phase 6) — only after Meet learns options basics
