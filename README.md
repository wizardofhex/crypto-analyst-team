# Crypto Analyst Team

A multi-agent AI trading analyst system built on Claude (claude-sonnet-4-6). Eleven analysts with distinct personalities respond to your questions with live market data, disagree with each other when warranted, and build a persistent memory of lessons learned from past calls.

---

## Table of Contents

1. [Analysts](#analysts)
2. [Quick Start](#quick-start)
3. [Terminal Chat Interface](#terminal-chat-interface)
4. [Streamlit Dashboard](#streamlit-dashboard)
5. [Recommendation Tracker](#recommendation-tracker)
6. [Lookback Memory](#lookback-memory)
7. [Technical Indicators](#technical-indicators)
8. [Supported Coins](#supported-coins)
9. [Data Sources](#data-sources)
10. [Architecture](#architecture)
11. [Database Schema](#database-schema)
12. [Running Tests](#running-tests)
13. [Claude Code Slash Commands](#claude-code-slash-commands)
14. [Paid Upgrade Paths](#paid-upgrade-paths)
15. [Troubleshooting](#troubleshooting)

---

## Analysts

| Name | Role | Personality snapshot |
|------|------|----------------------|
| **ARIA** | Technical Analyst | Precision-first, cites every indicator value, mild rivalry with MARCUS |
| **MARCUS** | Tape Reader | Old-school volume expert, blunt, skeptical of lagging indicators |
| **NOVA** | Macro / Catalyst | Big-picture thinker, connects sentiment cycles to price action |
| **VEGA** | Derivatives/Options | Ex-vol desk, reads options flow, IV skew, put/call ratios, gamma |
| **DELTA** | Futures/Perpetuals | OI obsessed, tracks liquidation cascades, basis trades, funding arb |
| **CHAIN** | On-Chain Analyst | Blockchain detective — exchange flows, MVRV, NUPL, whale tracking |
| **QUANT** | Quantitative Analyst | PhD-level stats, correlations, vol regimes, probability distributions |
| **DEFI** | DeFi/Yield Strategist | Protocol revenue, TVL trends, token economics, unlock schedules |
| **ATLAS** | Geopolitical/Regulatory | Policy advisor turned crypto — SEC actions, ETF flows, regulation |
| **REX** | Risk Manager | Capital preservation above all, always quotes stop/target/sizing |
| **ZEN** | Contrarian | Fades crowded trades, hunts FOMO/FUD extremes, devil's advocate |

Each analyst receives the same live market data but interprets it through their own lens. They see each other's prior responses and push back when they disagree. The analysis order places REX (risk) and ZEN (contrarian) last so they can synthesize and challenge the full team's output.

---

## Quick Start

### Prerequisites

- Python 3.10 or later
- An [Anthropic API key](https://console.anthropic.com)

### 1. Navigate to the project directory

```bash
cd crypto_analyst_team
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

This installs: `anthropic`, `rich`, `requests`, `pandas`, `numpy`, `yfinance`, `python-dotenv`, `streamlit`, `plotly`.

### 3. Configure your API key

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Then open `.env` and set:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run the terminal chat

```bash
python main.py
```

### 5. Run the dashboard (optional, separate terminal)

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501`. The dashboard and chat share the same `recommendations.db` — run them simultaneously.

---

## Terminal Chat Interface

### Free-form chat

Just type naturally. Mentioning any recognised coin symbol automatically fetches live data from CoinGecko and Binance and routes the question through all five analysts in sequence. Each analyst sees what the previous ones said.

```
You: What do you think about SOL right now?
```

To direct a question at one specific analyst, start the message with their name (or prefix with `@`):

```
You: ARIA, what does the RSI say about ETH?
You: @ZEN give me the contrarian case for BTC
You: REX, how should I size a SOL position here?
```

### Chat commands

| Command | Description |
|---------|-------------|
| `/analyze <COIN>` | Full five-analyst breakdown with live data fetched fresh |
| `/team` | Display analyst bios in a table |
| `/history` | Last 30 days of saved recommendations from the database |
| `/performance` | Analyst track records (win rate, avg return, best/worst call) + live P&L on open positions |
| `/lookback <COIN> <DAYS>` | AI-generated lessons-learned report for a coin over N days, saved as persistent memory |
| `/help` | Show all commands |

### Example session

```
You: What do you think about SOL?

[ARIA — Technical Analyst]
RSI on the 4H sitting at 67 — approaching overbought but not there yet.
MACD histogram is thinning, bearish divergence forming. 50 EMA at $142
holding as dynamic support. BB %B at 78% — upper band squeeze incoming.
WATCH for now. If RSI clears 70 on declining volume I'm flipping AVOID.

[MARCUS — Tape Reader]
Volume on this last leg was 23% below the 20-period SMA — that's
distribution disguised as a rally. Smart money selling into retail FOMO.
I want a volume surge above 150% of average before trusting this move.
WATCH. No conviction here.

[NOVA — Macro/Catalyst]
Fear & Greed at 72 (Greed). Funding rate at +0.018% — longs paying shorts,
elevated but not extreme. ARIA and MARCUS are right to be cautious,
but macro tailwinds are real. WATCH with bullish bias.

[REX — Risk Manager]
ATR is $8.40. Entry at $152, stop at $142.50 (below 50 EMA),
target $168 = R/R of 1.84:1. Size at 1–1.5% portfolio risk max.
Confidence: 5/10.

[ZEN — Contrarian]
Crypto Twitter is calling $200 SOL. FOMO detector is flashing.
The pain trade is a flush to $138-144 before any real continuation.
AVOID until we get that shakeout.

⚠️ For research purposes only — not financial advice.
```

---

## Streamlit Dashboard

Launch with `streamlit run dashboard.py` (opens at `http://localhost:8501`).

The dashboard reads `recommendations.db` in real time and auto-refreshes every 60 seconds.

### Pages

| Page | What it shows |
|------|--------------|
| **Overview** | Five KPI cards (win rate, total calls, closed P&L, open positions, avg confidence) · Fear & Greed gauge with 30-day trend · recent call feed · calls-per-analyst bar chart |
| **Leaderboard** | Ranked table with win rate, avg return, best/worst call, Sharpe-like ratio · gradient-coloured · win rate bar · avg return bar · radar spider chart |
| **Active Positions** | All OPEN recommendations enriched with live CoinGecko prices · unrealised P&L % · % distance to target and stop · rows coloured green/red by P&L |
| **Performance** | Cumulative win rate over time (per analyst, toggleable) · monthly volume stacked bar · confidence vs return scatter with trendline · analyst × coin avg return heatmap · cumulative P&L chart |
| **History** | Full recommendation history with filters: date range, analyst, coin, direction, status, outcome · CSV export button |
| **Coin Analysis** | 7-day price sparkline with open entry-price overlays · best/worst analysts for the coin · analyst agreement vs outcome scatter |
| **Lookback Insights** | All AI-generated post-mortems from `/lookback` commands, expandable by coin |

---

## Recommendation Tracker

The tracker (`tracker.py`) is a SQLite-backed store for analyst calls. It powers `/history`, `/performance`, and all dashboard pages.

### How calls get saved

When an analyst gives a clear LONG / SHORT / WATCH / AVOID / NEUTRAL stance with price levels, you can save it to the database using the Python API directly:

```python
from tracker import save_recommendation

rec_id = save_recommendation(
    analyst="ARIA",
    symbol="BTC",
    recommendation="LONG",   # must be one of LONG/SHORT/WATCH/AVOID/NEUTRAL
    entry_price=67500.0,
    target_price=74000.0,
    stop_loss=64000.0,
    confidence=7,            # 1–10
    thesis="Breakout above weekly resistance on high volume.",
    tags=["breakout", "weekly"],
)
```

### Closing a call

```python
from tracker import close_recommendation

# Returns the outcome % (positive = profit in direction of trade)
outcome_pct = close_recommendation(rec_id, close_price=73500.0)
# For a LONG from $67,500 closed at $73,500: outcome_pct ≈ +8.89%
# For a SHORT, sign is flipped automatically (falling price = profit)
```

Closing a call automatically updates that analyst's stats (`analyst_stats` table).

### Querying data

```python
from tracker import get_open_recommendations, get_recommendations_history, get_analyst_performance

# All currently open calls
open_recs = get_open_recommendations()

# Filtered: ARIA's BTC calls from the last 14 days
history = get_recommendations_history(symbol="BTC", days=14, analyst="ARIA")

# Performance stats for all analysts
stats = get_analyst_performance()

# Stats for one analyst
aria_stats = get_analyst_performance("ARIA")
```

### Validation rules

- `recommendation` is case-insensitive but must be one of `LONG`, `SHORT`, `WATCH`, `AVOID`, `NEUTRAL` — raises `ValueError` otherwise.
- `confidence` is clamped to the range 1–10.
- `status` when closing must be `OPEN`, `CLOSED`, or `EXPIRED`.

---

## Lookback Memory

The `/lookback` command is the system's learning mechanism.

```
/lookback BTC 30
```

This:

1. Retrieves every BTC recommendation from the past 30 days.
2. Sends them to Claude to generate a post-mortem with four sections:
   - **Key Patterns** — signals that correlated with accurate calls
   - **Failures** — where analysts went wrong and why
   - **Lessons Learned** — 3–5 specific, actionable lessons
   - **Bias Watch** — systematic team-wide biases to guard against
3. Saves the report to the `lookback_memory` table.
4. **Automatically injects the report** into every analyst's system prompt for all future BTC questions — this persists across sessions.

The memory is sanitised before injection (`agents.py::_sanitise_memory`) to strip control characters, null bytes, and known prompt-injection trigger phrases, and is capped at 2,000 characters.

View saved reports in the dashboard under **Lookback Insights**, or query them directly:

```python
from tracker import get_latest_lookback_memory
memory = get_latest_lookback_memory("BTC")
```

---

## Technical Indicators

All indicators are computed in `indicators.py` using pandas and numpy only (no TA-Lib dependency). They are calculated for multiple timeframes (15m, 1h, 4h, 1d) and injected into each analyst's context.

| Indicator | Parameters | Notes |
|-----------|-----------|-------|
| RSI | period=14 | Wilder's smoothing (EWM, com=period−1) |
| MACD | fast=12, slow=26, signal=9 | Line, signal, and histogram |
| Bollinger Bands | period=20, std=2.0 | Uses ddof=1 (sample std dev) |
| EMA | 9, 21, 50, 200 | Separate values for each period |
| SMA | 20, 50, 200 | Simple rolling means |
| ATR | period=14 | Wilder's smoothing; used by REX for stop placement |
| Stochastic RSI | rsi=14, stoch=14, K=3, D=3 | K and D smoothed, 0–100 scale |
| VWAP | — | Session-reset: resets at midnight UTC each day |
| Volume SMA | period=20 | Volume vs average expressed as a ratio % |
| Pivot Points | — | Standard: P, R1–R3, S1–S3, using previous candle |
| EMA cross signals | 9/21, 50/200 | Labelled bullish/bearish, golden/death cross |

Indicators require at least 30 candles to produce reliable values. Shorter series return `None` for most fields rather than raising errors.

---

## Supported Coins

The following symbols are recognised automatically in free-form chat and with `/analyze`:

```
BTC  ETH  SOL  BNB  XRP  ADA  DOGE  AVAX  DOT  LINK
MATIC  UNI  LTC  ATOM  NEAR  APT  OP  ARB  SUI  INJ
TIA  PEPE  WIF  BONK  TON  SHIB  FET  RENDER  IMX  SEI  HBAR
```

To add a coin, update `SYMBOL_TO_CG_ID` in `config.py` with its CoinGecko ID.

---

## Data Sources

All free — no API keys required for core functionality. Optional keys unlock additional data.

| Source | Endpoint | Data | Used by |
|--------|----------|------|---------|
| [CoinGecko](https://www.coingecko.com/en/api) | `/coins/{id}` | Price, market cap, 24h/7d change, ATH, volume | All |
| [Binance Spot](https://binance-docs.github.io/apidocs/spot/en/) | `/api/v3/klines` | OHLCV candles: 15m, 1h, 4h, 1d (200 each) | ARIA, MARCUS |
| [Binance Spot](https://binance-docs.github.io/apidocs/spot/en/) | `/api/v3/depth` | Order book (20 levels); bid/ask imbalance | MARCUS |
| [Binance Futures](https://binance-docs.github.io/apidocs/futures/en/) | `/fapi/v1/fundingRate` | Perpetual funding rate | NOVA, DELTA |
| [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | `/fng/` | Fear & Greed Index + 30-day history | NOVA, ZEN |
| [Yahoo Finance](https://pypi.org/project/yfinance/) | via `yfinance` | OHLCV fallback when Binance unavailable | ARIA |
| [Deribit](https://docs.deribit.com/) | `/public/get_book_summary_by_currency` | Options volume, put/call ratio (BTC/ETH only) | VEGA |
| [CoinGlass](https://coinglass.com/) | `/public/v2/open_interest` | Futures open interest + 24h change | DELTA |
| [Blockchain.com](https://www.blockchain.com/api) | `/stats` | BTC hash rate, difficulty | CHAIN |
| [Glassnode](https://glassnode.com/) | `/v1/metrics/market/mvrv` | MVRV ratio (requires API key) | CHAIN |
| [DeFiLlama](https://defillama.com/docs/api) | `/protocol/{slug}`, `/v2/chains` | TVL, TVL changes | DEFI |

### Optional API keys (in `.env`)

| Key | Unlocks |
|-----|---------|
| `GLASSNODE_API_KEY` | MVRV, NUPL on-chain metrics for CHAIN |
| `ETHERSCAN_API_KEY` | ETH on-chain stats for CHAIN |
| `COINGECKO_API_KEY` | Higher CoinGecko rate limits |

### Rate limits

- CoinGecko free tier: ~30 requests/min. The fetcher adds 80ms delays between timeframe fetches.
- Binance public endpoints: 1,200 requests/min weight limit. The system uses well under this.
- Alternative.me: No documented limit for the F&G endpoint.

---

## Architecture

```
crypto_analyst_team/
│
├── main.py          — Rich terminal UI, command routing, chat loop
├── dashboard.py     — Streamlit analytics dashboard (7 pages)
├── agents.py        — Eleven Analyst classes, Anthropic SDK, memory sanitisation
├── data_fetcher.py  — CoinGecko + Binance + Deribit + CoinGlass + DeFiLlama + Glassnode + more
├── indicators.py    — Pure pandas/numpy: RSI, MACD, BB, EMAs, ATR, StochRSI, VWAP, pivots
├── tracker.py       — SQLite CRUD: recommendations, analyst stats, lookback memory
├── performance.py   — Performance report generation, open P&L, lookback report via Claude
├── config.py        — Shared constants (DB_PATH, ANALYST_ORDER, COINGECKO_BASE, SYMBOL_TO_CG_ID)
│
├── tests/
│   ├── test_indicators.py   — RSI, MACD, BB, VWAP, calculate_all_indicators
│   ├── test_tracker.py      — save/close/query recommendations, analyst stats
│   └── test_data_fetcher.py — order book imbalance, CoinGecko ID mapping
│
├── .claude/
│   └── commands/
│       ├── traders.md    — /traders slash command
│       └── dashboard.md  — /dashboard slash command
│
├── .env.example     — API key template
├── requirements.txt — All dependencies
└── recommendations.db  — SQLite database (created on first run)
```

### Module dependencies

```
config.py
    └── imported by: data_fetcher, tracker, performance, main, agents

tracker.py
    └── imported by: performance, main, dashboard

data_fetcher.py
    └── imported by: agents (via format_market_data_for_prompt), performance, main, dashboard

indicators.py
    └── imported by: agents (via format_market_data_for_prompt), dashboard

performance.py
    └── imported by: main
```

---

## Database Schema

The SQLite database (`recommendations.db`) is created automatically on first run by `tracker.init_db()`.

### `recommendations`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | TEXT | UTC ISO-8601 timestamp when the call was made |
| `analyst` | TEXT | ARIA / MARCUS / NOVA / REX / ZEN |
| `symbol` | TEXT | Coin ticker, e.g. `BTC` |
| `recommendation` | TEXT | LONG / SHORT / WATCH / AVOID / NEUTRAL |
| `entry_price` | REAL | Price at time of recommendation |
| `target_price` | REAL | Price target (nullable) |
| `stop_loss` | REAL | Stop loss level (nullable) |
| `confidence` | INTEGER | 1–10, clamped on write |
| `thesis` | TEXT | Free-text rationale |
| `status` | TEXT | OPEN / CLOSED / EXPIRED |
| `close_price` | REAL | Actual close price (set when status changes) |
| `outcome_pct` | REAL | Realised P&L %; positive = profit in call direction |
| `closed_at` | TEXT | UTC timestamp of close |
| `tags` | TEXT | JSON array of string tags |

### `analyst_stats`

Aggregated from closed `recommendations` rows. Recalculated on every `close_recommendation()` call.

| Column | Description |
|--------|-------------|
| `analyst` | Primary key |
| `total_calls` | Count of closed calls |
| `wins` | Calls with `outcome_pct > 0` |
| `losses` | Calls with `outcome_pct < 0` |
| `total_return_pct` | Sum of all `outcome_pct` values |
| `best_call_pct` | Highest single `outcome_pct` |
| `worst_call_pct` | Lowest single `outcome_pct` |
| `updated_at` | Last recalculation timestamp |

### `lookback_memory`

| Column | Description |
|--------|-------------|
| `id` | Auto-increment PK |
| `symbol` | Coin the report covers |
| `days` | Look-back window used |
| `generated_at` | UTC timestamp |
| `summary` | Full AI-generated post-mortem text |

---

## Running Tests

The test suite uses `pytest` and covers `indicators.py`, `tracker.py`, and the pure functions in `data_fetcher.py`. Tests never touch the real `recommendations.db` — the tracker tests use a temporary database via `monkeypatch`.

```bash
# Install pytest if not already present
pip install pytest

# Run all tests
pytest tests/ -v

# Run one test file
pytest tests/test_indicators.py -v

# Run a specific test class
pytest tests/test_tracker.py::TestCloseRecommendation -v
```

### What the tests cover

**`test_indicators.py`**
- RSI output is in \[0, 100\], length matches input
- MACD histogram equals `macd_line − signal_line`
- Bollinger Bands use `ddof=1` (sample std dev), upper ≥ mid ≥ lower
- VWAP resets at midnight UTC (session-reset behaviour)
- `calculate_all_indicators` returns empty dict for DataFrames with fewer than 5 rows

**`test_tracker.py`**
- `save_recommendation` returns an integer ID; rejects invalid direction strings; clamps confidence to 1–10; normalises lowercase input to uppercase
- `get_recommendations_history` filters correctly by symbol, analyst, and date window
- `close_recommendation` computes LONG profit, SHORT profit, and LONG loss correctly; returns `None` for unknown IDs; raises `ValueError` for invalid status; auto-updates `analyst_stats`

**`test_data_fetcher.py`**
- `compute_order_book_imbalance` handles balanced, bid-heavy, ask-heavy, empty, and malformed inputs
- `get_coingecko_id` maps all symbols in `config.SYMBOL_TO_CG_ID` correctly, lowercases unknown symbols

---

## Claude Code Slash Commands

Two slash commands are registered in `.claude/commands/` for use inside Claude Code.

### `/traders`

Launches the terminal chat interface.

```
cd crypto_analyst_team && python main.py
```

### `/dashboard`

Launches the Streamlit dashboard.

```
cd crypto_analyst_team && streamlit run dashboard.py
```

---

## Paid Upgrade Paths

The system works entirely on free data. These services add depth when you're ready to invest:

| Service | Cost | What it adds |
|---------|------|--------------|
| [Polygon.io](https://polygon.io) | $29/mo | Real-time WebSocket feeds, tick-level trade data |
| [Glassnode](https://glassnode.com) | $29/mo | On-chain analytics: SOPR, MVRV, exchange net flows, whale activity |
| [Messari](https://messari.io) | $25/mo | Protocol fundamentals, token unlock schedules, research reports |
| [CoinAPI](https://www.coinapi.io) | $79/mo | Aggregated L2 order book across all major exchanges |
| [Alpaca](https://alpaca.markets) | Free tier | Trade execution API — paper trading and live, crypto + equities |

To wire up a paid source:
1. Add your key to `.env` (see `.env.example` for the variable names).
2. Add a fetch function to `data_fetcher.py`.
3. Extend `fetch_all_market_data()` to include the new data.
4. Update `format_market_data_for_prompt()` in `agents.py` to surface the data to analysts.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'config'`**
Run from inside `crypto_analyst_team/`, not its parent directory:
```bash
cd crypto_analyst_team
python main.py
```

**`ANTHROPIC_API_KEY is not set`**
Make sure `.env` exists (copy from `.env.example`) and contains your key.
`dashboard.py` reads the key from the environment — set it in your shell if needed:
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # macOS/Linux
set ANTHROPIC_API_KEY=sk-ant-...      # Windows cmd
$env:ANTHROPIC_API_KEY="sk-ant-..."   # Windows PowerShell
```

**`Database not found` in the dashboard**
The database is created when `main.py` first runs `init_db()`. Start the terminal chat at least once before opening the dashboard.

**CoinGecko returns a 429 error**
You've hit the free-tier rate limit (~30 req/min). Wait 60 seconds, or add a longer delay in `data_fetcher.py` between calls.

**Binance data unavailable (returns `None`)**
Some coins don't have a `<SYMBOL>USDT` pair on Binance. The fetcher falls back to yfinance automatically. If yfinance also fails, indicators that require OHLCV will be skipped and the analysts will note the missing data.

**Streamlit shows a blank page**
Make sure `recommendations.db` exists. If it doesn't, run `python main.py` first. The dashboard calls `st.stop()` if the database file is not found.

**`pytest` not found**
```bash
pip install pytest
```

---

⚠️ **For research and educational purposes only. Not financial advice.**
