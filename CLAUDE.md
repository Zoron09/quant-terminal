# QUANT TERMINAL — Project Specification

## Overview
A Bloomberg-style stock research terminal built with Python + Streamlit. Dark themed, mobile responsive, designed for SEPA/Minervini swing trading methodology. Supports US stocks (NYSE/NASDAQ) and Indian stocks (NSE/BSE).

## Tech Stack
- Python 3.11+
- Streamlit (web UI framework)
- yfinance (free stock data, 15-min delayed)
- pandas / numpy (data manipulation)
- plotly (interactive dark-themed charts)
- pypfopt (portfolio optimization, Phase 4)
- feedparser (news RSS feeds, Phase 3)
- requests (API calls)

Install all dependencies automatically via requirements.txt and pip.

## Design Rules
- DARK THEME ONLY: black/charcoal background (#0E1117), neon green accents (#00FF41), white text
- Red for negative values (#FF4444), green for positive (#00FF41), yellow for warnings (#FFD700)
- Bloomberg aesthetic: dense information, monospace fonts for numbers, data-first layout
- Every number right-aligned, every label left-aligned
- Color code everything: green = positive/bullish, red = negative/bearish
- Mobile responsive: single column on mobile, multi-column on desktop
- Use Streamlit dark theme in .streamlit/config.toml

## App Structure
- Sidebar: ticker search input at top, navigation tabs below
- User types a ticker like "AAPL" or "RELIANCE.NS" for Indian stocks
- Main content area shows the selected section for that ticker

---

## PHASE 1: Stock Profile and Fundamentals

Build these pages/tabs accessible from sidebar navigation:

### Tab 1: Overview (default landing page after ticker entry)

TOP BAR (always visible, sticky):
- Ticker symbol (large bold)
- Company name
- Current price (large, green if up, red if down vs previous close)
- Dollar change and percent change
- Market status badge: "LIVE" (green) or "CLOSED" (gray)
- Data source: yfinance info dict

SECTION A - Company Snapshot (2-column layout):
Left column:
- Sector
- Industry
- Country
- Full-time employees (formatted with commas)
- Website (clickable link)
- Top 3 company officers/executives

Right column:
- Market cap (formatted as $XX.XXB or $XX.XXM)
- Enterprise value
- Shares outstanding
- Float shares
- Average volume 10-day
- Average volume 3-month

SECTION B - Business Description:
- Collapsible/expandable section with longBusinessSummary
- Default: collapsed

SECTION C - Key Statistics (grid of metric cards, 3-4 columns):

Valuation metrics:
- Trailing P/E
- Forward P/E
- Price to Book
- Price to Sales (TTM)
- EV/EBITDA
- PEG Ratio

Profitability metrics:
- EPS (trailing)
- EPS (forward)
- Profit margin (as %)
- Operating margin (as %)
- Return on equity (as %)
- Return on assets (as %)

Trading metrics:
- Beta
- 52-week high
- 52-week low
- 50-day moving average
- 200-day moving average
- Short ratio

Dividend info:
- Dividend rate
- Dividend yield (as %)
- Ex-dividend date
- Payout ratio

Each metric card should show the label, value, and be color-coded where appropriate (e.g., low P/E = green, high P/E = yellow/red).

### Tab 2: Financial Statements

Three sub-tabs: Income Statement, Balance Sheet, Cash Flow

INCOME STATEMENT:
- Show annual data for last 5 years and quarterly for last 8 quarters
- Toggle between annual and quarterly view
- Key rows: Revenue, Cost of Revenue, Gross Profit, Operating Expenses, Operating Income, Net Income, EPS (Basic), EPS (Diluted)
- Highlight row showing year-over-year growth % for each metric
- Color code: positive growth green, negative red
- Source: yfinance Ticker.financials and Ticker.quarterly_financials

BALANCE SHEET:
- Same annual/quarterly toggle
- Key rows: Total Assets, Total Liabilities, Total Equity, Cash and Equivalents, Total Debt, Net Debt, Book Value Per Share
- Source: yfinance Ticker.balance_sheet and Ticker.quarterly_balance_sheet

CASH FLOW:
- Same annual/quarterly toggle
- Key rows: Operating Cash Flow, Capital Expenditure, Free Cash Flow, Dividends Paid, Share Buybacks
- Highlight Free Cash Flow prominently
- Source: yfinance Ticker.cashflow and Ticker.quarterly_cashflow

FORMAT: Display as a styled table with alternating row backgrounds. Numbers in monospace font. Negative numbers in red with parentheses.

### Tab 3: Growth and Margins Charts

REVENUE AND EARNINGS CHART:
- Dual-axis bar chart: revenue as bars, net income as bars (different colors)
- Line overlay showing revenue growth % and earnings growth %
- Both annual (5yr) and quarterly (8Q) toggle
- Plotly interactive chart, dark theme

MARGIN TRENDS CHART:
- Line chart with 3 lines: Gross Margin %, Operating Margin %, Net Margin %
- Annual view (5 years) and quarterly view
- Show exact values on hover
- Include a horizontal reference line at 0%

EPS GROWTH CHART:
- Bar chart showing EPS by quarter
- Color bars green when EPS grew vs same quarter prior year, red when declined
- Show growth % labels on each bar
- This is critical for SEPA methodology (earnings acceleration)

### Tab 4: Valuation and Ratios

RATIO DASHBOARD (2x3 grid of mini charts):
Each chart shows the metric over time (5 years quarterly):
- P/E ratio trend
- P/S ratio trend
- EV/EBITDA trend
- P/B ratio trend
- ROE trend
- ROIC trend (calculate from financials: NOPAT / Invested Capital)

DCF VALUATION MODEL:
- Simple DCF calculator with editable inputs
- Inputs: Current FCF, Growth rate (5yr), Terminal growth rate, Discount rate (WACC)
- Pre-fill with sensible defaults from company data
- Output: Estimated intrinsic value per share
- Show margin of safety: (intrinsic value - current price) / intrinsic value as %
- Color code: green if undervalued, red if overvalued

PIOTROSKI F-SCORE:
- Calculate all 9 criteria automatically from financial statements
- Display as a scorecard: each criterion with pass (green check) or fail (red x)
- Show total score out of 9
- Criteria: positive net income, positive ROA, positive operating cash flow, cash flow > net income, lower long term debt ratio, higher current ratio, no new shares issued, higher gross margin, higher asset turnover
- Source: calculate from yfinance financial statements

### Tab 5: Earnings

EARNINGS CALENDAR:
- Next earnings date from yfinance
- Countdown timer (days until next earnings)

EARNINGS HISTORY TABLE:
- Last 12 quarters
- Columns: Date, EPS Estimate, EPS Actual, Surprise %, Revenue Estimate, Revenue Actual
- Color code: beat = green, miss = red
- Source: yfinance Ticker.earnings_dates

EARNINGS SURPRISE CHART:
- Bar chart showing the EPS surprise % for each quarter
- Green bars for beats, red for misses

ANALYST ESTIMATES:
- Current quarter and next quarter EPS estimates
- Current year and next year EPS estimates
- Number of analysts
- Source: yfinance earnings_estimate, revenue_estimate

### Tab 6: Analyst Ratings

CONSENSUS RATING:
- Large display showing Buy/Overweight/Hold/Underweight/Sell
- Visual gauge or donut chart showing distribution of ratings
- Total number of analysts

PRICE TARGETS:
- Current price vs Low / Average / High price target
- Visual bar showing where current price sits in the range
- Upside/downside % from current price to average target

UPGRADES AND DOWNGRADES:
- Recent history table: Date, Firm, Action (upgrade/downgrade/initiate), From Rating, To Rating
- Source: yfinance Ticker.upgrades_downgrades

### Tab 7: Ownership

INSIDER TRANSACTIONS:
- Table: Date, Insider Name, Title, Transaction (Buy/Sell), Shares, Value
- Highlight buys in green, sells in red
- Summary: Net insider buying/selling over last 3/6/12 months
- Source: yfinance Ticker.insider_transactions

INSTITUTIONAL HOLDERS:
- Top 15 institutional holders table
- Columns: Holder Name, Shares Held, % of Outstanding, Value, Date Reported
- Source: yfinance Ticker.institutional_holders

MUTUAL FUND HOLDERS:
- Top 15 mutual fund holders
- Source: yfinance Ticker.mutualfund_holders

OWNERSHIP SUMMARY:
- Pie chart: Insiders vs Institutions vs Retail/Other
- Insider ownership %
- Institutional ownership %

### Tab 8: Peer Comparison

PEER TABLE:
- Automatically find 5-8 peers in same sector/industry
- Comparison columns: Ticker, Price, Market Cap, P/E, P/S, EPS Growth, Revenue Growth, Profit Margin, ROE, Beta, RS Rating
- Highlight the selected stock's row
- Color code each metric: best in sector = green, worst = red
- Sortable columns

---

## PHASE 2: SEPA Engine and Screener (build after Phase 1 works)

### Tab 9: SEPA Analysis

TREND TEMPLATE CHECKLIST:
All 8 Minervini criteria with auto pass/fail:
1. Price above 150-day MA
2. Price above 200-day MA
3. 150-day MA above 200-day MA
4. 200-day MA trending up for at least 1 month
5. 50-day MA above 150-day MA and 200-day MA
6. Price above 50-day MA
7. Price at least 25% above 52-week low
8. Price within 25% of 52-week high
- Show PASS count: X/8
- Overall verdict: SEPA QUALIFIED (green, 7-8 pass) or NOT QUALIFIED (red)

STAGE ANALYSIS:
- Determine current Weinstein stage: 1 (Basing), 2 (Advancing), 3 (Topping), 4 (Declining)
- Show visual indicator of current stage

RS RANKING:
- Calculate relative strength vs S&P 500 (or Nifty for Indian stocks) over 6 and 12 months
- Show percentile rank 1-99
- SEPA wants 70+ minimum
- Show RS line chart (stock price / index price over time)

VCP DETECTION:
- Identify volatility contraction patterns in recent price data
- Show number of contractions detected
- Visual chart highlighting VCP pattern on price chart

EARNINGS ACCELERATION:
- Last 4-8 quarters EPS growth rate
- Flag if growth is accelerating
- Visual chart showing acceleration or deceleration

COMPOSITE SEPA SCORE:
- Weighted score combining: Trend template (30%), RS ranking (20%), Earnings acceleration (20%), VCP pattern (15%), Volume characteristics (15%)
- Score out of 100
- Grade: A (80+), B (60-79), C (40-59), D (below 40)

### Tab 10: Stock Screener

SCREENER INTERFACE:
- Dropdown to select market: US or India
- Combinable filter sections:

Technical Filters:
- Price vs 50/150/200 MA (above/below)
- RS Ranking minimum (slider 0-99)
- Volume vs average (minimum multiplier)
- 52-week high proximity (within X%)

Fundamental Filters:
- Market cap range (min/max)
- P/E range
- Revenue growth % minimum
- EPS growth % minimum
- Profit margin minimum

SEPA Filters:
- Minimum trend template score (X/8)
- Minimum SEPA composite score
- VCP detected (yes/no)
- Earnings accelerating (yes/no)

PRE-BUILT SCANS (one-click buttons):
- "SEPA Candidates" — trend template 7+/8, RS 80+, earnings accelerating
- "Breakout Watch" — within 5% of 52-week high, volume surge, Stage 2
- "High RS Leaders" — RS ranking 90+, Stage 2
- "Earnings Momentum" — 3+ quarters accelerating EPS growth
- "New Highs" — hit new 52-week high recently
- "Volume Surge" — today volume 2x+ average

RESULTS TABLE:
- Sortable columns: Ticker, Company, Price, Change%, Market Cap, P/E, RS Rank, SEPA Score, Stage, Trend Template
- Click any row to load that stock
- Export to CSV button

NOTE: Use pre-built universe. US: S&P 500 + NASDAQ 100. India: Nifty 500. Store ticker lists in JSON files. Show progress bar during scans. Cache results.

---

## PHASE 3: News and Sentiment (build after Phase 2)

### Tab 11: News and Sentiment

NEWS FEED:
- Per-stock news using Google News RSS, Yahoo Finance RSS
- Show: Headline, Source, Time ago, Link
- Auto-refresh every 5 minutes

SEC FILINGS:
- Pull from SEC EDGAR free API for US stocks
- Show recent 10-K, 10-Q, 8-K filings with direct links

PRICE ALERTS:
- User sets price alerts stored in local JSON
- Check on each refresh, show notification when triggered

---

## PHASE 4: Portfolio and Risk Management (build after Phase 3)

### Tab 12: Portfolio Manager

PORTFOLIO INPUT:
- Manual entry: Ticker, Shares, Average Cost
- Save to local JSON, support multiple portfolios

PORTFOLIO DASHBOARD:
- Total value, total gain/loss, daily change
- Holdings table with all relevant columns
- Pie chart: allocation by stock and sector

PORTFOLIO OPTIMIZER (pypfopt):
- Max Sharpe, Min Volatility, Risk Parity portfolios
- Recommended vs current weights
- Efficient frontier chart

RISK METRICS:
- Portfolio beta, Sharpe, Sortino, max drawdown, VaR (95%), correlation matrix heatmap

POSITION SIZE CALCULATOR:
- Inputs: Account size, risk %, entry price, stop loss
- Output: shares to buy, dollar risk

BACKTESTING:
- Input tickers, weights, date range
- Output: total return, CAGR, max drawdown, Sharpe, equity curve, drawdown chart, monthly returns heatmap
- Benchmark vs S&P 500

---

## PHASE 5: Market Overview (build after Phase 4)

### Tab 13: Market Dashboard

INDICES: S&P 500, NASDAQ, Dow, Nifty 50, Sensex, Russell 2000 with sparklines

SECTOR HEATMAP: Sector ETFs colored by daily performance

MARKET BREADTH: Advance/decline, % above 50MA, % above 200MA

FEAR AND GREED PROXY: VIX-based gauge with color coding

ECONOMIC CALENDAR: Major dates (FOMC, CPI, Jobs, GDP)

CURRENCIES AND COMMODITIES: USD/INR, Gold, Oil, 10Y Treasury, Bitcoin

---

## PHASE 6: Options (build last)

### Tab 14: Options

OPTIONS CHAIN: Full chain with expiry selector, calls/puts, Greeks
IMPLIED VOLATILITY: IV chart over time, IV percentile
P/L CALCULATOR: Strategy selector with payoff diagram
GREEKS DASHBOARD: Delta, Gamma, Theta, Vega with plain English tooltips

---

## File Structure
```
quant-terminal/
├── CLAUDE.md
├── requirements.txt
├── .streamlit/
│   └── config.toml
├── app.py
├── pages/
│   ├── 01_overview.py
│   ├── 02_financials.py
│   ├── 03_growth_margins.py
│   ├── 04_valuation_ratios.py
│   ├── 05_earnings.py
│   ├── 06_analyst_ratings.py
│   ├── 07_ownership.py
│   ├── 08_peer_comparison.py
│   ├── 09_sepa_analysis.py
│   ├── 10_screener.py
│   ├── 11_news_sentiment.py
│   ├── 12_portfolio.py
│   ├── 13_market_dashboard.py
│   └── 14_options.py
├── data/
│   ├── sp500_tickers.json
│   ├── nifty500_tickers.json
│   └── portfolios.json
├── utils/
│   ├── data_fetcher.py
│   ├── sepa_engine.py
│   ├── portfolio_engine.py
│   ├── dcf_model.py
│   ├── piotroski.py
│   └── formatters.py
└── styles/
    └── custom.css
```

## Caching Strategy
- Price data: cache 15 minutes
- Financial statements: cache 24 hours
- News: cache 1 hour
- Show "last updated" timestamp on each section

## Error Handling
- If yfinance field returns None, show "N/A" in gray
- If API call fails, show error with retry button
- Indian stocks: append .NS or .BO suffix
- Auto-detect market: if ticker contains "." assume Indian, otherwise US

## Build Instructions
Build phase by phase. Start with Phase 1 only. Each phase must be fully functional before moving to next. Install all Python dependencies automatically. Create Streamlit dark theme config. Everything runs with: streamlit run app.py
