# Quant Terminal — Design System

## Overview

**Quant Terminal** is a Bloomberg-style stock research and screening terminal built for serious retail traders who follow Mark Minervini's **SEPA methodology** (Stage Analysis / Earnings / Price / Volume Acceleration). It runs locally via Streamlit at `localhost:8501`.

The product is a solo tool built for **Meet Singh** (Delhi, India → NSW Australia), with zero coding experience — so all complexity is hidden behind a clean UI. The terminal aggregates data from Alpaca, yfinance, Finnhub, and SEC EDGAR across 13+ pages.

### Sources

- **Codebase:** `github.com/Zoron09/quant-terminal` (main branch)
- **CSS:** `styles/custom.css` — original Bloomberg dark theme (being redesigned)
- **App entry:** `app.py` (Overview page)
- **Pages:** 13 Streamlit pages covering everything from financial statements to live screening

---

## Products / Surfaces

| Surface | Files | Description |
|---|---|---|
| **Stock Overview** | `app.py` | Top bar, company snapshot, key stats, dividends |
| **Financials** | `pages/2_Financials.py` | IS/BS/CF statements, annual/quarterly |
| **Growth & Margins** | `pages/3_Growth_and_Margins.py` | Revenue, EPS, margin charts |
| **Valuation** | `pages/4_Valuation.py` | Ratios, DCF model, Piotroski F-Score |
| **Earnings** | `pages/5_Earnings.py` | Calendar, history, surprises, estimates |
| **Analyst Ratings** | `pages/6_Analyst_Ratings.py` | Consensus, price targets |
| **Ownership** | `pages/7_Ownership.py` | Insider transactions, institutional holders |
| **Peer Comparison** | `pages/8_Peer_Comparison.py` | Sector peers, color-coded metrics |
| **SEPA Analysis** | `pages/9_SEPA_Analysis.py` | Trend template, VCP, Code 33, RS rank |
| **Screener** | `pages/10_Screener.py` | Full US market scan, SQLite cache, 6 presets |
| **News & Sentiment** | `pages/11_News_Sentiment.py` | Finnhub/Alpaca news, SEC filings, price alerts |
| **Portfolio** | `pages/12_Portfolio.py` | Real-time P&L, optimizer, risk metrics |
| **Market Dashboard** | `pages/13_Market_Dashboard.py` | Indices, sector heatmap, VIX, breadth |

---

## Content Fundamentals

### Tone & Voice
- **Direct, data-first.** No fluff. Every label earns its space.
- **Professional but not corporate.** This is a personal power tool, not a bank dashboard.
- **No marketing copy.** All text is functional: labels, statuses, values, descriptions.
- **Short labels:** "Profit Margin" not "Net Profit Margin as a %". Abbreviate: "Avg Vol (10D)", "52-Wk High".
- **ALL CAPS for section headers** and labels within data tables (terminal aesthetic).
- **Title Case for page names** and navigation items.

### Casing
- Section headers: `ALL CAPS` — e.g. `VALUATION`, `COMPANY SNAPSHOT`
- Metric labels: Title Case — e.g. `Trailing P/E`, `Market Cap`
- Status/badge text: ALL CAPS — e.g. `LIVE`, `CLOSED`, `SEPA QUALIFIED`
- Body text (descriptions): Sentence case

### Numerics
- All financial numbers right-aligned
- Large numbers shortened: `$1.23B`, `$456M`, `2.3K`
- Percentages with `+` prefix for positive: `+12.34%`
- Prices with 2 decimal places: `$184.26`
- All numbers in monospace font
- Color-coded: green = positive/good, red = negative/bad, amber = caution

### Emoji
- **Not used** in the redesign. Original codebase used page icon emoji (📊, 🌐, etc.) but these are removed in the new system. Use iconography instead.

### Terminology
- SEPA = Stage Analysis, Earnings, Price, Volume Acceleration (Minervini)
- VCP = Volatility Contraction Pattern
- Code 33 = EPS + Revenue acceleration + Margin expansion simultaneously
- RS = Relative Strength rank
- MA = Moving Average (50MA, 150MA, 200MA)

---

## Visual Foundations

### Color System
See `colors_and_type.css` for all tokens. Summary:

| Role | Token | Value |
|---|---|---|
| Page background | `--bg-base` | `#070B12` |
| Surface (cards) | `--bg-surface` | `#0D1420` |
| Surface raised | `--bg-raised` | `#111B2E` |
| Border subtle | `--border-subtle` | `#1A2640` |
| Border default | `--border` | `#243650` |
| Accent / primary | `--accent` | `#3ECFCF` (electric teal) |
| Accent secondary | `--accent-2` | `#6366F1` (indigo) |
| Positive | `--positive` | `#22C55E` |
| Negative | `--negative` | `#F43F5E` |
| Warning | `--warning` | `#F59E0B` |
| Text primary | `--fg-1` | `#EDF2F7` |
| Text secondary | `--fg-2` | `#94A3B8` |
| Text muted | `--fg-3` | `#475569` |

### Typography
- **Numbers/data:** JetBrains Mono (Google Fonts) — replaces Courier New. Cleaner, more modern, same terminal feel.
- **UI labels/text:** DM Sans — clean, geometric sans-serif. Pairs well with mono.
- See `colors_and_type.css` for full scale.

### Backgrounds
- Deep navy-black base, no pure black — gives depth without the harsh contrast of #000000.
- No gradients on backgrounds. Gradients only on accent overlays (subtle, 8% opacity max).
- No background images or textures. Data IS the texture.

### Cards
- Background: `--bg-surface` (`#0D1420`)
- Border: 1px solid `--border` (`#243650`)
- Border radius: `6px` (small — terminal precision, not rounded consumer UI)
- Left-accent border: `3px solid --accent` for primary metric cards
- No box-shadow — uses border instead
- Padding: `12px 16px`
- Hover: background lightens to `--bg-raised` (`#111B2E`)

### Spacing
- Base unit: `4px`
- Tokens: `--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-5: 20px`, `--space-6: 24px`, `--space-8: 32px`

### Borders & Radius
- Default radius: `6px`
- Small (badges/chips): `3px`
- Large (modals/overlays): `8px`
- NO fully rounded (pill) elements except status badges

### Animations
- Minimal. Data updates: instant (no animation).
- Hover transitions: `150ms ease` opacity or background-color only.
- No bounces, springs, or decorative motion. This is a professional tool.

### Hover States
- Cards: background lightens (no shadow appears)
- Buttons: 10% lighter background
- Table rows: `--bg-raised` background
- Links (ticker symbols): color stays accent, underline appears

### Icons
- Lucide Icons (CDN) — thin stroke, clean geometric. See ICONOGRAPHY section.

### Imagery
- No decorative imagery. Charts are the visual content.
- Chart colors follow semantic tokens: green/red for pos/neg, accent for primary lines.
- Chart backgrounds: `--bg-surface`, grid lines: `--border-subtle`

---

## Iconography

**Icon system: Lucide Icons** (`https://unpkg.com/lucide@latest`)
- Stroke-based, 1.5px weight, clean geometric
- Size: 16px inline, 20px for standalone actions
- Color: inherits from context (fg-2 for muted, accent for active)
- No filled icons in the main UI

**Key icons used:**
- `trending-up` / `trending-down` — price direction
- `bar-chart-2` — market data, screener
- `activity` — live/streaming status
- `search` — screener input
- `filter` — filter controls
- `star` — watchlist
- `bell` — price alerts
- `briefcase` — portfolio
- `globe` — market dashboard
- `file-text` — financials
- `zap` — SEPA / Code 33 signal
- `shield` — risk metrics
- `clock` — earnings calendar

No emoji used as icons. No custom SVG illustrations. No PNG icons.

---

## Files

| File | Description |
|---|---|
| `README.md` | This file — master design reference |
| `colors_and_type.css` | All CSS custom properties: colors, type, spacing |
| `SKILL.md` | Agent skill definition |
| `preview/` | Design system card HTMLs (shown in Design System tab) |
| `ui_kits/terminal/` | Full HTML UI kit — interactive terminal prototype |

---

## UI Kit

See `ui_kits/terminal/index.html` — an interactive prototype of the redesigned terminal covering:
- Stock Overview page (top bar + key stats)
- Market Dashboard (indices, sector heatmap, VIX)
- SEPA Analysis (trend template, Code 33 status)
- Screener results table
