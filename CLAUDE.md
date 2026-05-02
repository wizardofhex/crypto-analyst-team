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
  ├── run_scheduled_analysis.py  — Headless LLM-team runner (12h cron)
  |     Analyzes BTC/ETH (RPL dropped under v2 plan), no-setup gate, saves to DB, pushes to GitHub
  |
  ├── run_deterministic_strategy.py — Headless rule-based runner (12h cron, Strategy B)
  |     Pre-registered rules using indicators.py, writes to recommendations_deterministic table
  |
  ├── run_hold_monitor.py — Weekly RPL long-term hold monitor (10K RPL position)
  |     7-analyst subset in HOLD mode, recommends HOLD/ADD/TRIM/EXIT, writes to hold_recommendations
  |
  ├── pre_mortem_tests.py — Weekly evaluator for v2 hypothesis tests (H1-H4)
  |     SQL-only checks against DB state, writes to hypothesis_tests table
  |
  └── main.py — Interactive terminal chat (local use)
        Rich UI, /analyze, /team, /lookback commands
```

**Strategy structure (v2 plan, 2026-05-02):** the system runs three competing strategies in parallel —
HODL benchmark, deterministic rule-based (Strategy B), and the 11-persona LLM team (Strategy C).
All three share the same 12-hour cadence, 48-hour time-stops, and database storage. Week 4
decision rules (in `IMPLEMENTATION_PLAN_v2.md`) compare them and pick the survivor.

**Hold portfolio (v2 + hold extension, 2026-05-02):** RPL is OUT of the active trading universe
but tracked as a long-term hold position (10K units). Monitored weekly via `run_hold_monitor.py`
or `SKILL_rpl_hold.md` in Cowork. Decision space is HOLD/ADD/TRIM/EXIT — not LONG/SHORT.

**Cowork-native operation:** `SKILL.md`, `SKILL_deterministic.md`, `SKILL_rpl_hold.md`, and
`SKILL_premortem.md` cover all four scheduled jobs without requiring local Python. See
`COWORK_SCHEDULED_TASKS.md` for the cron entries.

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
# Default (v2): analyze BTC + ETH with Haiku and push DB to GitHub
python run_scheduled_analysis.py BTC ETH --push

# Analyze specific coins (RPL dropped under v2 plan due to thin liquidity)
python run_scheduled_analysis.py BTC ETH AVAX LINK --push

# Use Sonnet for higher signal quality
python run_scheduled_analysis.py BTC ETH --model claude-sonnet-4-6 --push

# Use Opus 4.7 (~5× cost over Sonnet)
python run_scheduled_analysis.py BTC ETH --model claude-opus-4-7 --push

# Without pushing to GitHub
python run_scheduled_analysis.py BTC ETH

# Run the deterministic baseline strategy (Strategy B) in parallel
python run_deterministic_strategy.py BTC ETH --push
```

**Cost per run (2 coins, 11 analysts each = 22 API calls), at the 12h cadence (2 runs/day):**
- Haiku 4.5:  ~$0.008/run → ~$0.50/month
- Sonnet 4.6: ~$0.10/run  → ~$6/month
- Opus 4.7:   ~$0.45/run  → ~$27/month

The no-setup gate (Item #1) typically skips 50–70% of runs entirely on coins with no qualifying
trigger, further reducing cost.

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

- **Dashboard**: 