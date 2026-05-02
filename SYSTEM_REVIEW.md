# Crypto Analyst Team — System Review and Improvement Plan

_Generated 2026-05-02 from a review of the live repo, four weeks of database history, and the 4/20 + 5/2 weekly lookbacks._

---

## Part 1 — How the system works today

### 1.1 What it is, in one sentence

A multi-agent LLM trading-analysis loop that fires on a 4-hour cron, runs 11 specialized "analyst" personas over BTC/ETH/RPL using live market data, persists the resulting LONG/SHORT/WATCH signals to a SQLite database, and renders the whole thing on a public Streamlit dashboard. The portfolio is paper-traded against a $124,000 notional.

### 1.2 Architecture

There are three independent runtime paths into the same database:

- **`run_scheduled_analysis.py`** — the headless production runner. Invoked by a cron-like scheduler every 4 hours. It pulls live data, calls Claude (currently Sonnet 4.6 by default for cost; Opus 4.7 for highest signal quality), parses signals, writes to `recommendations.db`, and pushes the updated DB to GitHub. The push triggers Streamlit Cloud to redeploy automatically.

- **`main.py`** — an interactive Rich-styled terminal chat for ad-hoc analysis. Same engine underneath, plus slash commands like `/analyze BTC`, `/team`, `/lookback SOL 30`, and natural-language commands like `close my BTC long`.

- **`crypto-4h-analysis-cowork` skill** — a fallback path that runs inside Cowork on the same 4-hour cron, 30 minutes after the local Python runner. It detects whether the local runner already produced fresh signals (rows < 45 min old) and skips silently if so. Otherwise it replicates the full pipeline using inline Python and curl, since the Cowork sandbox can't always reach Binance and doesn't have the Anthropic Python SDK installed for the analyst calls (the cowork skill roleplays the analysts directly).

The Streamlit dashboard auto-deploys from `wizardofhex/crypto-analyst-team` on every push and is served at `crypto.rocketph.one` via a Vercel redirect.

### 1.3 The 11 analysts

Each analyst is a persona definition in `agents.py` — a system prompt, a name, a domain, and a position in the run order. They run sequentially. The first analyst sees only market data; each subsequent analyst additionally sees every prior analyst's output for the current coin in the current run. This is intentional so the late-stage seats can synthesize and challenge.

| # | Name | Domain | Why it runs in this slot |
|---|------|--------|--------------------------|
| 1 | ARIA | Technical (RSI, MACD, BB, EMA stack) | First — pure tape read, no peer influence |
| 2 | MARCUS | Tape reader (volume, order flow, candle structure) | Early — confirms or contradicts ARIA |
| 3 | NOVA | Macro/catalyst/sentiment (F&G, news, funding direction) | Adds context layer |
| 4 | VEGA | Derivatives/options (PCR, IV, max pain) | BTC/ETH only — RPL has no liquid options |
| 5 | DELTA | Futures/perpetuals (OI, funding, liquidations) | Cross-checks VEGA |
| 6 | CHAIN | On-chain (exchange flows, MVRV, NUPL, whales) | Mid-stack synthesis |
| 7 | QUANT | Quantitative (vol regime, correlations, statistical edges) | Mid-stack synthesis |
| 8 | DEFI | DeFi/yield (TVL, protocol revenue, token unlocks) | Mid-stack synthesis |
| 9 | ATLAS | Geopolitical/regulatory (SEC, ETF flows, policy) | Wide-context layer |
| 10 | REX | Risk manager (stops, sizing, R/R, exposure caps) | Late — sees almost the full team |
| 11 | ZEN | Contrarian (fades crowded trades, FOMO/FUD) | Last — sees everyone, designed to disagree |

The run-order matters in two ways. First, late seats can read what early seats said and either reinforce (which produces the herding problem the lookbacks have flagged) or fade (which is what REX and ZEN are *supposed* to do but rarely do in practice). Second, REX's directive output (see §1.7) gates ZEN's sizing rules, so REX must run before ZEN.

### 1.4 Signal format and persistence

Every analyst is required to end its response with one line in this exact format:

```
[SIGNAL: LONG|SHORT|WATCH|AVOID|NEUTRAL | CONFIDENCE: N | TARGET: $X | STOP: $Y | SIZE: P% ($USD) | THESIS: one-sentence rationale]
```

The runner parses this with a regex (kept in sync between `main.py` and `run_scheduled_analysis.py` because both insert to the same DB). Only LONG and SHORT signals get persisted as positions. WATCH/AVOID/NEUTRAL are logged in the markdown report but never become open trades. Confidence is 1–10. Position size is denominated as a percentage of the $124,000 portfolio.

A row in `recommendations` carries: timestamp (ISO-8601 with `+00:00`), analyst, symbol, recommendation, entry/target/stop prices, confidence, thesis text, status (`OPEN`/`CLOSED`/`EXPIRED`), close price, outcome percentage, closed-at timestamp, position size in both percent and dollars, and a JSON `tags` array used for run-quality filtering on the dashboard.

### 1.5 Data sources

Each data source is a method in `data_fetcher.py` with try/except fallthrough, so a failure in one source degrades signal quality rather than killing the run.

| Source | Provides | Used by |
|--------|----------|---------|
| CoinGecko | Spot price, market cap, ATH, 24h volume | All analysts |
| Binance | OHLCV candles (15m/1h/4h/1d), order book, funding rate | ARIA, MARCUS, DELTA |
| Deribit | Options put/call ratio, IV, volume (BTC/ETH only) | VEGA |
| CoinGlass | Open interest snapshots, 24h OI delta | DELTA |
| DeFiLlama | TVL, TVL change across 20+ protocols | DEFI |
| Blockchain.com | BTC hashrate, mining difficulty | CHAIN |
| Glassnode | MVRV, NUPL (requires `GLASSNODE_API_KEY`) | CHAIN |
| Alternative.me | Fear & Greed Index | NOVA, ZEN |

In the Cowork fallback path, Binance is geo-blocked (HTTP 451) and Bybit hits a CloudFront block, so substitutes are used: Kraken for BTC/ETH OHLC, Coinbase for RPL OHLC, OKX for funding and OI. Cowork runs are tagged `cowork-fallback` so the dashboard can distinguish them.

### 1.6 Indicators

`indicators.py` is pure pandas/numpy — no TA-Lib dependency. It computes RSI, MACD (with signal and histogram), Bollinger Bands (with %B), EMA-9/21/50/200, SMA-20/50/200, Stochastic RSI (K and D), ATR, VWAP (omitted for 4h+ timeframes since it's meaningless across multi-day windows), volume SMA-20 with ratio, and pivot points (R1/R2/R3, S1/S2/S3). It also computes flag values like `golden_cross` (50-SMA above 200-SMA), `ema_9_21_cross` (bullish/bearish), and last-candle metadata (body ratio, doji flag, bullish/bearish).

The output is a flat dict of *current candle* values, which gets injected into each analyst's prompt as context. Analysts see numeric reality, not just narrative.

### 1.7 The 4/20 guardrails

The 2026-04-20 weekly lookback identified three recurring failures the original system didn't prevent:

1. The team would go 96/94/91% LONG with sub-35% win rates — 11 analysts piling into one direction was treated as "diversified" but acted as one large position.
2. REX traded the team's narrative book (28/28 LONG on BTC, 27/1 on ETH) — the risk manager wasn't actually challenging anything.
3. ZEN fired lone-SHORT contrarian fades on vibes and lost about −4% per ETH call on average.

Three guardrails were added in response, all enforced in §4.5 of the cowork skill and the equivalent step in the local runner. They are read-only SQLite queries against `recommendations.db`, no new schema:

**Exposure caps** — measured per coin against the open book. WARN at ≥10% of portfolio in one direction; HARD CAP at ≥15%. Hitting the HARD CAP forces any same-direction call to downgrade to WATCH or size ≤0.5% ($620).

**Cooldown** — if there's been a closed losing position on a coin within the last 12 hours, any new same-direction call must cite a *new* signal absent from the losing thesis or downgrade.

**Confidence calibration** — rolling 30-day per-(analyst, coin, confidence bucket) win rate, surfaced to the analyst before it writes its call. If the analyst's conf=7 bucket on this coin had a sub-25% win rate over the last 30 days, a conf=7 call today is presumed overconfidence.

**REX EXPOSURE_BLOCK directive** — REX must emit one extra line immediately before its `[SIGNAL: ...]` line: `EXPOSURE_BLOCK: YES` or `EXPOSURE_BLOCK: NO`. YES is mandatory whenever same-direction notional ≥ 10% of portfolio or 5+ analysts in this round are pointing the same direction. ZEN parses this directive and downgrades accordingly.

**ZEN numeric-trigger gate** — ZEN may publish LONG or SHORT *only* if at least one of these is true with the actual cited value: funding > +0.05% / < −0.05%, F&G ≥ 75 / ≤ 25, P/C > 1.3 / < 0.6, or 7+ aligned analysts in this round. Without a trigger, ZEN must emit WATCH or NEUTRAL.

**Cohort split** — to break the "late seats anchor on early seats" cascade, the 11 analysts are now split into two cohorts. Cohort 1 (ARIA, MARCUS, NOVA, VEGA, DELTA) runs *blind* — each one derives its call from market data and its own guardrail block only, with the emit order randomized across runs. Cohort 2 (CHAIN, QUANT, DEFI, ATLAS, REX, ZEN) runs sequentially and is allowed to synthesize.

These guardrails first executed under the cowork fallback in the 5/2 12:32Z run. They've existed for one run as of the time of this document.

### 1.8 Database

SQLite at `recommendations.db`, three tables (plus `analysis_reports` for the dashboard's history page and `analyst_stats` for win/loss tracking).

`recommendations` is the main table — one row per emitted LONG/SHORT signal, lifecycle-managed (status flips OPEN → CLOSED when target/stop is hit or position is manually closed).

`lookback_memory` stores AI-generated lessons-per-coin from the weekly lookback runner. These get *injected back* into future analyst prompts as historical context — the system remembers what failed last week.

`analyst_stats` is denormalized win/loss counters per analyst, refreshed by `tracker.update_analyst_stats()`.

### 1.9 Position lifecycle

A position opens when a LONG/SHORT signal is parsed and persisted. It closes via three paths:

1. **Target hit** — `tracker.check_and_close_positions(symbol, current_price)` runs at the start of every scheduled run, before new signals are inserted. It scans OPEN rows for the symbol, compares current price to target/stop, and flips status to CLOSED with the appropriate `outcome_pct`.

2. **Stop hit** — same function, mirror logic.

3. **Manual close** — only via the interactive `main.py` chat ("close my BTC long" or `/close`). Headless runs never manually close.

There is currently **no time-based auto-close**. A position with target far above price and stop far below price can sit OPEN indefinitely. The database has at least one such case: a SOL SHORT marked −74% / −$1,369 unrealized.

### 1.10 Cost structure

Per scheduled run (3 coins × 11 analysts = 33 API calls):

| Model | Per run | Per month at 4h cadence |
|-------|--------:|------------------------:|
| Haiku 4.5 | ~$0.012 | ~$2.20 |
| Sonnet 4.6 | ~$0.14 | ~$25 |
| Opus 4.7 | ~$0.70 | ~$125 |

The weekly lookback runner adds about $0.05/week regardless of model, since it makes only 3 calls (one per coin) over a small input window.

### 1.11 Performance to date

Database covers 2026-04-04 → 2026-05-02 (~28 days, 706 closed trades).

- Realized closed P&L: **+$188** (37% win rate, avg trade −0.19%)
- Unrealized open P&L marked at current prices: **+$1,891**
- Combined: **+$2,079 = +1.68%** on a $124K portfolio over four weeks

Underneath the flat headline:

- BTC trades: **+$10,220** realized (avg +1.47%, mostly LONG, mostly worked)
- ETH trades: **−$9,671** realized (avg −1.56%, the lookbacks identified this as the herding/cascade problem)
- RPL trades: **−$322** realized
- SOL: **−$39** realized plus the orphan SOL SHORT at unrealized −$1,369

Recent trend: last 7d was −$4,904 at 24% win rate, last 14d was −$6,302 at 31%. So the period that ended up break-even was "good first three weeks, ugly final week."

Top earners by analyst: REX (+$1,190), MARCUS (+$533), CHAIN (+$375). Bleeders: DEFI (16% win rate, −$1,625), ATLAS (32%, −$510), ZEN (41%, −$333 across 70 trades).

---

## Part 2 — Potential improvements and optimizations

The headline diagnosis from four weeks of data and two weekly lookbacks is that **this isn't a portfolio of 11 independent analysts — it's one analyst run 11 times with cosmetic differences, fired far too often.** Most of the changes below address some flavor of that.

### 2.1 High-leverage structural changes

**A. Cut cadence from 4h to 12h or 1d.** The lookbacks are explicit that what worked was extreme-volume capitulations and BB-edge exhaustions. Those events happen a few times per week, not six times per day. Running every 4h forces the team to find a trade in chop, where the lookback says they consistently lose. A lower cadence reduces noise, lowers cost from ~$25/mo to ~$8/mo on Sonnet, and likely raises win rate without any model or prompt changes.

**B. Add a "no-setup, no-trade" precondition.** Before spending an LLM call on 11 analysts, evaluate cheaply: is anything actually worth analyzing right now? Fire the full team only if at least one of these is true on the coin in question:
- ATR(4h) > 1.3× its 20-period mean (vol expanding)
- Price within 1 ATR of a key structural level (200 EMA, 7d high/low, prior pivot)
- |funding| > 0.05% (positioning extreme)
- F&G ≤ 25 or ≥ 75 (sentiment extreme)
- 24h price move > 2 ATR (regime break)

If none are true, emit "no setup, no trade" and skip the LLM calls entirely. This is a one-day implementation in `run_scheduled_analysis.py` before the analyst loop. Conservative estimate: 50–70% of runs would skip, which is the right answer for those runs.

**C. Stop treating the 11 analysts as independent for sizing.** Compute the historical signal-correlation matrix from the DB. ARIA, QUANT, MARCUS, and DELTA likely have signal correlations north of 0.7 — they're all reading the same OHLC tape with different framings. If that's true, then 4 LONGs at 0.5% each isn't 2% diversified exposure; it's 2% concentrated exposure. **Cap aggregate per-coin exposure at 5%** regardless of how many "independent" votes pile in. The HARD CAP guardrail addresses the >15% case but should kick in much earlier.

**D. Force REX and ZEN to default to WATCH unless they can write a fresh thesis.** REX trades the book under "balancing" framing — the lookback nailed this exact failure: *"book-balancing SHORTs added real directional risk while framed as hedges, disguising true net exposure."* Make WATCH the default for both seats, and require a paragraph (>75 words, no reference to other analysts' calls) explaining the standalone thesis to upgrade to LONG/SHORT. ZEN's gate is already in place but the role still tries to fire on every coin every run; the prompt should explicitly say *most runs should produce NEUTRAL on most coins*.

### 2.2 Smaller fixes that compound

**E. Time-based auto-close.** Every LONG/SHORT that hasn't hit target or stop within 48 hours auto-closes at mark price with status `EXPIRED`. Add to `tracker.py` and call from `check_and_close_positions`. The orphan SOL SHORT sitting at −74% for a month is the textbook case — that one position is worth almost as much as the entire 4-week realized P&L (−$1,369 vs +$188).

**F. Quit RPL or size it down 5×.** RPL has $1.78M daily volume across all venues. The team's combined open notional already shows $43K LONG + $9K SHORT — a not-trivial fraction of daily turnover. Either drop RPL from the rotation entirely or cap RPL position size at 0.1% ($124). Running 0.5% on RPL is a different risk profile than 0.5% on BTC, and the lookbacks confirm it: RPL shorts work when there's an obvious 145× volume capitulation print and lose otherwise, which is a thinner edge than BTC's.

**G. Confidence-weighted, calibration-weighted sizing.** Right now a conf=3 marginal call gets the same $620 as a conf=8 conviction call. Make size proportional to (`confidence × calibration_score`) clipped to the HARD CAP. The calibration score is the rolling 30-day per-(analyst, coin, confidence-bucket) win rate that's already computed in §4.5 of the cowork skill but isn't actually used for sizing — only for guidance text injected into the prompt. Wire it into the math.

**H. Add a buy-and-hold benchmark to the dashboard.** What did 1/3 BTC + 1/3 ETH + 1/3 RPL do over the same window starting 2026-04-04? If naive HODL beats the team, the system has negative alpha and is paying API fees for the privilege. The 4/4 → 5/2 window includes a notable BTC move that buy-and-hold would have captured cleanly while the team partially wrote it off with offsetting ETH losses. Knowing the benchmark is the difference between "the system needs tuning" and "the system needs rethinking."

**I. Tag and track guardrail-version. ** Every persisted row should carry a `guardrails_version` tag. `guardrails-v1` exists already. After two weeks of data under v1, compare win rates against pre-guardrail rows. If v1 demonstrably improved win rate, tighten further. If not, the underlying problem is signal generation, not enforcement, and the fixes need to move further upstream into the analyst prompts themselves.

### 2.3 Higher-effort, higher-payoff changes

**J. Decorrelate the analyst panel.** ARIA + QUANT + MARCUS + DELTA are functionally redundant — they're all looking at the same close-price series with different lenses. The lookbacks confirm they often vote together and lose together. Either fold them into a smaller composite (e.g., one "Tape" analyst that internally weighs RSI/MACD/EMA/volume) or genuinely diversify by giving each a *non-overlapping* data domain. ATLAS (geopolitics) and DEFI (TVL/unlocks) are the only seats with truly independent signal sources today, and they happen to have low signal-correlation with the rest — which is precisely why they should be weighted *more*, not less.

**K. Regime-aware prompting.** The system today uses the same prompts in trending markets, ranging markets, high-vol markets, and low-vol markets. The lookbacks identified that *trend-continuation in mid-range was the worst trade pattern*; this is a regime-specific failure. A simple regime classifier (price relative to 200 EMA, ATR percentile, BB width percentile) injected into every prompt would let analysts adapt: "we are in low-vol mid-range — fade extremes, do not chase trend."

**L. Backtest the guardrails before trusting them.** The 4/20 guardrails are well-motivated by the lookback findings, but they've executed in production for exactly one run as of this document. Replay the last 28 days of market data through the guardrail logic in dry-run mode and measure: would the v1 rules have prevented the ETH cascade? If yes, ship them with confidence. If they would have only prevented some of it, layer on additional rules until they cover the actual failure modes.

**M. Per-coin model selection.** Sonnet 4.6 is the current default. Opus 4.7 is 5× the cost. The interesting question is whether Opus is worth it on BTC (where signal quality matters because position sizes are largest) but not on RPL (where the edge is thin and noise dominates). A two-tier setup — Opus on BTC, Haiku on RPL, Sonnet on ETH — might deliver near-Opus aggregate quality at near-Sonnet aggregate cost.

### 2.4 What I'd actually do this week

If it were my project, in this order:

1. Add the no-setup precondition (item B). One-day implementation; immediately kills the largest source of bad trades.
2. Add 48h time-stop (item E). Half-day; clears stale junk including the SOL position.
3. Switch cadence to 12h (item A). One-line config change.
4. Add buy-and-hold benchmark to the dashboard (item H). One afternoon. This will tell you whether the rest of the work is worth doing — if HODL is winning, the answer is to make the system pickier (items A/B/D), not "smarter" (items J/K).

After two weeks of data under the new regime, revisit items C, F, G, I. Those need real before/after data to validate, not vibes.

What I'd resist is adding *more* analysts or more data sources. The lookbacks aren't telling you the team is missing information — they're telling you the team is acting on too much information at marginal setups. The fix is fewer, better trades, not richer prompts.

---

_This document is a system review based on database state and lookback findings as of 2026-05-02. It is not financial advice. The system trades on a paper portfolio; production deployment of any of these changes should be staged behind the existing tag-based dashboard filtering so pre/post-change behavior can be compared cleanly._
