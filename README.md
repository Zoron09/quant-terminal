# Quant Terminal

Quantitative stock screener based on 
Minervini's Code 33 methodology.

## Run
pip install fastapi uvicorn yfinance pandas feedparser python-multipart requests
python run.py
Open http://localhost:8000

## How it works
1. Export stock list from TradingView as CSV
2. Upload to Screener
3. Code 33 engine scans every ticker
4. Winners shown as cards
5. Click card → full stock overview
