Launch the Crypto Analyst Team Streamlit analytics dashboard.

Opens at http://localhost:8501 — a dark-themed trading terminal UI with 7 pages:
- Overview: KPI cards, Fear & Greed gauge, auto-refresh every 60s
- Leaderboard: Win rate, avg return, Sharpe ratio, radar spider chart
- Active Positions: Live unrealized P&L from CoinGecko prices
- Performance: Cumulative win rate, confidence vs return scatter, analyst × coin heatmap
- History: Searchable/filterable full call history with CSV export
- Coin Analysis: 7-day price chart, best analysts per coin
- Lookback Insights: AI-generated lessons from /lookback reports

Requires recommendations.db to exist — run `python main.py` at least once first.

cd crypto_analyst_team && streamlit run dashboard.py
