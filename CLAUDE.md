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

| # | Name | Role | Cohort | Order In Cohort |
|---|------|------|:---:|:---:|
| 1 | **ARIA** | Technical Analyst (RSI, MACD, BB, EMA) | 1 (parallel) | — |
| 2 | **MARCUS** | Tape Reader (volume, order flow, price action) | 1 (parallel) | — |
| 3 | **NOVA** | Macro/Catalyst (sentiment, funding rates, news) | 1 (parallel) | — |
| 4 | **VEGA** | Derivatives/Options (put/call, IV, gamma, max pain) | 1 (parallel) | — |
| 5 | **DELTA** | Futures/Perpetuals (OI, liquidations, basis) | 1 (parallel) | — |
| 6 | **CHAIN** | On-Chain (exchange flows, MVRV, NUPL, whales) | 2 (sequential) | 1st |
| 7 | **QUANT** | Quantitative (correlations, vol regimes, stats) | 2 (sequential) | 2nd |
| 8 | **DEFI** | DeFi/Yield (TVL, protocol revenue, unlocks) | 2 (sequential) | 3rd |
| 9 | **ATLAS** | Geopolitical/Regulatory (SEC, ETF flows, policy) | 2 (sequential) | 4th |
| 10 | **REX** | Risk Manager (stops, sizing, R/R, EXPOSURE_BLOCK) | 2 (sequential) | 5th |
| 11 | **ZEN** | Contrarian (gated by numeric triggers) | 2 (sequential) | 6th |

**Cohort 1 runs in parallel — no analyst sees another's response.** This
breaks the ordering-bias cascade identified in the 2026-04-20 lookback
(analysts 6–11 were rubber-stamping the first five). Display order of cohort 1
is randomized per run. Cohort 2 runs sequentially and sees the full cohort 1
transcript because those seats are explicit synthesizers.

REX (#10) runs second-to-last so his `EXPOSURE_BLOCK: YES/NO` directive can be
parsed and injected into ZEN's guardrail context before ZEN runs. See
`docs/LOOKBACK_RECS_20260420.md` for the full rationale.

## Key Files

| File | Purpose |
|------|---------|
| `agents.py` | All 11 analyst persona definitions + prompt construction |
| `config.py` | `ANALYST_ORDER`, `PORTFOLIO_SIZE` ($124K), `SYMBOL_TO_CG_ID` |
| `data_fetcher.py` | CoinGecko, Binance, Deribit, CoinGlass, DeFiLlama, Blockchain.com |
| `indicators.py` | RSI, MACD, BB, EMA, ATR, StochRSI, VWAP, pivots (pure pandas/numpy) |
| `tracker.py` | SQLite CRUD for recommendations, analyst stats, lookback memory |
| `guardrails.py` | Pre-prompt exposure / cooldown / confidence-calibration guardrails |
| `performance.py` | Performance reports, open P&L, lookback post-mortems (v2 helpers) |
| `main.py` | Interactive Rich terminal UI with /commands |
| `dashboard.py` | Streamlit web dashboard (7 pages) |
| `run_scheduled_analysis.py` | Headless runner (two-cohort parallel/sequential) |
| `start.py` | Launcher (starts dashboard + chat together) |

## Guardrail Invariants (added 2026-04-20)

The scheduled runner enforces these invariants before each analyst call. See
`docs/LOOKBACK_RECS_20260420.md` for the full rationale.

- **Exposure guard.** Same-direction open notional on a coin ≥10% of portfolio
  triggers a WARNING block; ≥15% triggers a HARD CAP that forces downstream
  analysts to WATCH or ≤0.5% sizing.
- **Cooldown guard.** Any CLOSED losing position on a coin within the last
  12h injects a re-entry warning into every subsequent analyst's prompt on
  that coin.
- **Confidence calibration.** Each analyst sees their own rolling 30-day
  conf→outcome history for the coin they're about to call. Inverted
  calibration (high-conf = low win-rate) is surfaced in-prompt.
- **REX EXPOSURE_BLOCK.** REX **must** emit `EXPOSURE_BLOCK: YES` or `:NO` on
  every call. The runner parses this and passes the directive into ZEN's
  guardrail context. Missing directives log `rex-missing-exposure-block-<SYM>`
  in the run's `tags` field.
- **ZEN numeric trigger.** ZEN may only publish LONG/SHORT when at least one
  of funding rate / F&G / put-call ratio / 7+ team alignment hits a defined
  threshold. No trigger → mandatory WATCH/NEUTRAL.

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

# Use Sonnet instead of Haiku (more expensive but higher quality)
python run_scheduled_analysis.py BTC ETH SOL --model claude-sonnet-4-6 --push

# Without pushing to GitHub
python run_scheduled_analysis.py BTC ETH SOL
```

**Cost per run (3 coins, 11 analysts each = 33 API calls):**
- Haiku: ~$0.012/run → ~$8.60/month hourly
- Sonnet: ~$0.14/run → ~$100/month hourly

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
- Never hardcode API keys — use environment variables
- Use `logger` (Python logging) not print() in library code
- Signal parsing regex is in `main.py` and `run_scheduled_analysis.py` — keep them in sync
- Tests in `tests/` with `test_` prefix, run with `pytest tests/ -v`
