# Crypto Analyst Team — Project Instructions

## What This Is

A multi-agent AI trading analysis system with **11 specialized analyst personas**. Each analyst receives live market data, sees prior analysts' responses, and produces directional signals (LONG/SHORT/WATCH) that are persisted to a SQLite database. Results are displayed on a live Streamlit dashboard.

## Architecture

```
GitHub: wizardofhex/crypto-analyst-team (public)
  |
  ├── Streamlit Cloud Dashboard (auto-deploys on push)
  |     URL: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/
  |     Domain: crypto.rocketph.one (via Vercel redirect)
  |
  ├── run_scheduled_analysis.py  — Headless runner (cron/scheduled use)
  |     Analyzes BTC/ETH/SOL, saves to DB, pushes to GitHub
  |
  └── main.py — Interactive terminal chat (local use)
        Rich UI, /analyze, /team, /lookback commands
```

## The 11 Analysts

| # | Name | Role | Runs In Order |
|---|------|------|:---:|
| 1 | **ARIA** | Technical Analyst (RSI, MACD, BB, EMA) | 1st |
| 2 | **MARCUS** | Tape Reader (volume, order flow, price action) | 2nd |
| 3 | **NOVA** | Macro/Catalyst (sentiment, funding rates, news) | 3rd |
| 4 | **VEGA** | Derivatives/Options (put/call, IV, gamma, max pain) | 4th |
| 5 | **DELTA** | Futures/Perpetuals (OI, liquidations, basis) | 5th |
| 6 | **CHAIN** | On-Chain (exchange flows, MVRV, NUPL, whales) | 6th |
| 7 | **QUANT** | Quantitative (correlations, vol regimes, stats) | 7th |
| 8 | **DEFI** | DeFi/Yield (TVL, protocol revenue, unlocks) | 8th |
| 9 | **ATLAS** | Geopolitical/Regulatory (SEC, ETF flows, policy) | 9th |
| 10 | **REX** | Risk Manager (stops, sizing, R/R) | 10th |
| 11 | **ZEN** | Contrarian (fades crowded trades, FOMO/FUD) | 11th |

REX and ZEN run last so they can synthesize and challenge the full team's output.

## Key Files

| File | Purpose |
|------|---------|
| `agents.py` | All 11 analyst persona definitions + prompt construction |
| `config.py` | `ANALYST_ORDER`, `PORTFOLIO_SIZE` ($124K), `SYMBOL_TO_CG_ID` |
| `data_fetcher.py` | CoinGecko, Binance, Deribit, CoinGlass, DeFiLlama, Blockchain.com |
| `indicators.py` | RSI, MACD, BB, EMA, ATR, StochRSI, VWAP, pivots (pure pandas/numpy) |
| `tracker.py` | SQLite CRUD for recommendations, analyst stats, lookback memory |
| `performance.py` | Performance reports, open P&L, lookback post-mortems |
| `main.py` | Interactive Rich terminal UI with /commands |
| `dashboard.py` | Streamlit web dashboard (7 pages) |
| `run_scheduled_analysis.py` | Headless runner for cron/scheduled execution |
| `start.py` | Launcher (starts dashboard + chat together) |

## Data Sources

| Source | Data | Used By |
|--------|------|---------|
| CoinGecko | Price, market cap, ATH, volume | All |
| Binance | OHLCV candles (15m, 1h, 4h, 1d), order book, funding rate | ARIA, MARCUS, DELTA |
| Deribit | Options put/call ratio, volume (BTC/ETH only) | VEGA |
| CoinGlass | Open interest, 24h OI change | DELTA |
| DeFiLlama | TVL, TVL changes (20+ protocols) | DEFI |
| Blockchain.com | BTC hashrate, difficulty | CHAIN |
| Glassnode | MVRV (requires GLASSNODE_API_KEY) | CHAIN |
| Alternative.me | Fear & Greed Index | NOVA, ZEN |

## How to Run the Scheduled Analysis

```bash
# Default: analyze BTC, ETH, SOL with Haiku and push DB to GitHub
python run_scheduled_analysis.py BTC ETH SOL --push

# Analyze specific coins
python run_scheduled_analysis.py BTC ETH SOL AVAX LINK --push

# Use Opus 4.7 (current default — best signal quality)
python run_scheduled_analysis.py BTC ETH SOL --model claude-opus-4-7 --push

# Use Sonnet for ~5× lower cost at modest quality trade-off
python run_scheduled_analysis.py BTC ETH SOL --model claude-sonnet-4-6 --push

# Without pushing to GitHub
python run_scheduled_analysis.py BTC ETH SOL
```

**Cost per run (3 coins, 11 analysts each = 33 API calls), at the 4h cadence (6 runs/day):**
- Haiku 4.5:  ~$0.012/run → ~$2.20/month
- Sonnet 4.6: ~$0.14/run  → ~$25/month
- Opus 4.7:   ~$0.70/run  → ~$125/month  (current default — verify against live per-token rates)

## How to Run Interactively

```bash
python main.py                    # Default model
python main.py --model sonnet     # Use Sonnet
python main.py --model haiku      # Use Haiku (cheapest)
```

### Terminal Commands
| Command | What It Does |
|---------|-------------|
| `/analyze BTC` | Full 11-analyst breakdown with live data |
| `/team` | Show all analyst profiles |
| `/history` | Last 30 days of recommendations |
| `/performance` | Track records + open positions |
| `/lookback SOL 30` | Generate lessons-learned report, saved as memory |
| `@ARIA what do you think about ETH?` | Direct question to specific analyst |
| `close my BTC long` | Close a position by natural language |

## Signal Format

Analysts emit signals at the end of their responses:
```
[SIGNAL: LONG | CONFIDENCE: 7 | TARGET: $185 | STOP: $162 | SIZE: 2.1% ($2,604) | THESIS: breakout above key resistance]
```

LONG/SHORT signals are automatically saved to `recommendations.db`. WATCH/AVOID/NEUTRAL are logged but not persisted.

## Database

SQLite at `recommendations.db` with 3 tables:
- `recommendations` — all LONG/SHORT calls with entry/target/stop/outcome
- `analyst_stats` — win/loss/return tracking per analyst
- `lookback_memory` — AI-generated lessons per coin (injected into future prompts)

## Deployment

- **Dashboard**: Streamlit Community Cloud, auto-deploys from `wizardofhex/crypto-analyst-team` on push
- **Domain**: `crypto.rocketph.one` → Vercel redirect project (`wizardofhex/rocketphone-redirects`) → Streamlit
- **DB sync**: `run_scheduled_analysis.py --push` commits and pushes updated `recommendations.db` to GitHub, triggering Streamlit redeploy

## Environment Variables

Required:
```
ANTHROPIC_API_KEY=sk-ant-...
```

Optional (enhance specific analysts):
```
GLASSNODE_API_KEY=...      # CHAIN: MVRV, NUPL on-chain metrics
ETHERSCAN_API_KEY=...      # CHAIN: ETH on-chain stats
COINGECKO_API_KEY=...      # All: higher rate limits
COINBASE_API_KEY=...       # MARCUS: authenticated order book
COINBASE_API_SECRET=...    # MARCUS: Coinbase CDP auth
```

## Adding a New Analyst

1. Add entry to `ANALYST_CONFIGS` dict in `agents.py`
2. Add name to `ANALYST_ORDER` list in `config.py` (position matters — later = sees more prior responses)
3. Add color to `COLOR` dict in `main.py`
4. Add hex color to `ANALYST_COLORS` dict in `dashboard.py`
5. Optionally add a data fetcher in `data_fetcher.py` and formatter in `agents.py`

## Adding a New Coin

Add to `SYMBOL_TO_CG_ID` in `config.py`:
```python
"NEWCOIN": "coingecko-api-id",
```

## Coding Standards

- Python 3.10+ with type hints
- All data fetchers must handle errors gracefully (try/except, return None on failure)
- Never hardcode API 