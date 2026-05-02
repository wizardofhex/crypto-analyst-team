# Crypto Analyst Team — Implementation Plan

**Date:** 2026-05-02
**Source:** Synthesis of `SYSTEM_REVIEW.md` plus three independent LLM analyses (Gemini, Grok, ChatGPT) on top of that review.
**Ordering:** By estimated impact on portfolio P&L, win rate, and decision quality — most impactful first.
**Portfolio:** $124,000 paper account, 11-persona LLM analyst team writing to `recommendations.db`.

---

## Impact-ordered backlog

Each item below carries: what it does, why it matters, where in the codebase it lands, the change in concrete terms, success criteria, and an effort estimate. Items further down may depend on data produced by items higher up — that's noted where it applies.

---

### 1. No-setup precondition gate

**What it does.** Before spending an LLM call on the 11-analyst loop for a given coin, evaluate cheaply whether *anything is actually unusual* about that coin right now. If nothing is, skip the entire analyst loop for that coin in this run, log a "no-setup-skip" row, and move on.

**Why it's #1.** The 4/20 and 5/2 lookbacks both identify mid-range trend-continuation as the single largest source of losses. The current 4h schedule forces the team to find a trade in chop, where the team consistently loses. This change directly stops the worst trades from being entered at all. Estimated to skip 50-70% of analyst loops — that's both a P&L improvement (fewer bad calls) *and* a 50-70% cost reduction.

**Where.** New file `regime_filter.py` (or a function in `data_fetcher.py`). Called from `run_scheduled_analysis.py` at the top of the per-coin loop, before the analyst calls.

**Concrete logic.**
```python
def has_setup(symbol, indicators, market_data) -> tuple[bool, str]:
    """Return (should_run_team, reason). False reason logs the skip."""
    triggers = []
    if indicators['atr'] / indicators.get('atr_20bar_mean', 1) > 1.3:
        triggers.append('vol_expanding')
    if is_within_atr_of_level(price, indicators['ema_200'], 1.0):
        triggers.append('near_200ema')
    if is_within_atr_of_level(price, indicators['week_high'], 1.0):
        triggers.append('near_week_high')
    if is_within_atr_of_level(price, indicators['week_low'], 1.0):
        triggers.append('near_week_low')
    if abs(market_data['funding_rate']) > 0.0005:  # > 0.05%
        triggers.append('funding_extreme')
    if market_data['fng'] <= 25 or market_data['fng'] >= 75:
        triggers.append('sentiment_extreme')
    if abs(market_data['change_24h_pct']) > 2 * indicators['atr_pct']:
        triggers.append('big_move_24h')
    return (len(triggers) > 0, ','.join(triggers) if triggers else 'no-setup')
```

**Tagging.** Every signal row written under the new gate gets `setup-gate-v1` in `tags`. Skipped runs write a single row to a new `skip_log` table (or the existing `analysis_reports` with `signals_count=0` and a `skip_reason` field).

**Success criteria.** Within two weeks: total signals/week drops by 50-70%, win rate on the signals that *do* fire rises by 5+ percentage points vs the pre-gate 4-week baseline, realized P&L per trade improves.

**Effort.** 1 day implementation, 1 day review and tuning of thresholds.

**Dependencies.** None. Ship first.

---

### 2. Regime-aware prompting (Grok's specification)

**What it does.** Classify each coin's current market regime into one of six states and inject that classification, along with adapted reasoning instructions, into every analyst's prompt. The analyst sees not just RSI=53 but "we are in LOW_VOL_CONTRACTION — trend-following calls require exceptional confirmation."

**Why it's #2.** This directly addresses the #1 finding from both lookbacks: *trend-continuation in mid-range was the worst trade pattern*. The current prompts are regime-blind — analysts apply the same logic in trending and ranging markets. A regime label changes the analyst's default behavior without any code changes to signal parsing or sizing.

**Where.** Add `classify_regime()` to `indicators.py`. Modify prompt construction in `agents.py` to inject the regime block above the data block.

**The six regimes.**
- `STRONG_UPTREND` — price > EMA200, 7d return > +5%, ATR ratio normal-to-high
- `STRONG_DOWNTREND` — mirror image
- `HIGH_VOL_EXPANSION` — ATR ratio > 1.5×, BB width > 80th percentile
- `LOW_VOL_CONTRACTION` — ATR ratio < 0.7×, BB width < 25th percentile
- `RANGE_BOUND_MID` — within 1 ATR of EMA50, RSI 40-60, no recent expansion
- `BREAKOUT_EXHAUSTION` — RSI > 75 or < 25, BB%B > 95 or < 5

**Injected context block.**
```
=== MARKET REGIME ===
Coin: ETH
Regime: RANGE_BOUND_MID / LOW_VOL_CONTRACTION
Price: $2,304 | EMA200: $2,259 (+2.0%)
ATR(14) ratio: 0.71× | BB width pctile: 22nd
RSI(14): 53.9
Implication: Low-conviction environment. Trend-continuation calls require
fresh catalyst PLUS volume confirmation. Default toward WATCH unless setup
matches a high-edge pattern (capitulation, blow-off, level rejection).
=====================
```

**Per-regime instruction text appended to each persona prompt.**
> "You are operating in the {REGIME} regime. Adapt your analysis: in RANGE_BOUND_MID and LOW_VOL_CONTRACTION, be highly skeptical of trend-following. Default to WATCH/NEUTRAL unless you can cite exceptional confirmation. Explicitly reference how the regime influences your thesis and risk parameters in your reasoning."

**Tagging.** Every signal carries the regime it was generated under: `regime-RANGE_BOUND_MID`, etc. The dashboard can then segment performance by regime — directly revealing whether the system has any edge in any regime, or only specific ones.

**Success criteria.** Win rate in RANGE_BOUND_MID and LOW_VOL_CONTRACTION should approach the team's overall win rate (currently those regimes drag it down). Win rate in BREAKOUT_EXHAUSTION and HIGH_VOL_EXPANSION should rise — those are the regimes the lookback identified as the team's actual edge.

**Effort.** 2-3 days. The classifier is straightforward; the prompt rewrites need a careful pass per persona.

**Dependencies.** Tier 1 #1 gate runs ahead of this (filter first, then classify). No data dependency.

---

### 3. HODL benchmark on the dashboard

**What it does.** Compute and display the value over time of a naive 1/3 BTC + 1/3 ETH + 1/3 RPL portfolio anchored at the database start date (2026-04-04), alongside the team's mark-to-market portfolio value.

**Why it's #3.** Without this, every other change here is unfalsifiable. "Did the system improve?" has no honest answer if the only baseline is "the system before." If HODL is winning, the right move is to make the system *pickier* (items 1, 2, 4, 5) rather than smarter. If HODL is losing, the team has real alpha and the optimization work is worth it.

**Where.** New page in `dashboard.py`: "Performance vs HODL." Anchor date = `MIN(timestamp)` from `recommendations`. Daily rebalance optional (probably not needed for a 28-day window).

**Computation.** At anchor date, allocate $124K/3 to each of BTC, ETH, RPL at the date's close price. Mark daily using CoinGecko historical or by sampling current `recommendations` `entry_price` rows. Subtract the team's net P&L at each timestep (realized + unrealized) for the comparison.

**Success criteria.** The chart simply exists and is honest. Two metrics on the page: (a) cumulative outperformance vs HODL since anchor, (b) rolling 7-day outperformance.

**Effort.** 1 afternoon.

**Dependencies.** None.

---

### 4. Cadence reduction 4h → 12h

**What it does.** Change the cron schedule for the production runner from every 4 hours (6 runs/day) to every 12 hours (2 runs/day).

**Why it's #4.** Compounds with #1. Even with the no-setup gate, fewer total scheduled runs means fewer total LLM calls and fewer chances to find a marginal trade. The lookbacks confirm that the trades that worked were extreme-volume capitulations and BB-edge exhaustions — events that occur a few times per week, not 12+ times per day. The 4h cadence forces the system to react to noise that doesn't matter at the chosen timeframe.

**Where.** Scheduled-tasks config (the `crypto-4h-analysis` task). Update CRON from `0 */4 * * *` to `0 */12 * * *`. Update the cowork fallback skill (`SKILL.md` skip-if-fresh threshold from 2700s → 21600s). Update `CLAUDE.md` cost estimates.

**Success criteria.** Run rate drops to 2/day; combined cost (with #1 active) drops to roughly $3-5/month on Sonnet. Trade quality should not visibly degrade.

**Effort.** 1 hour. One-line config change plus skill update.

**Dependencies.** Item #1 should be live first so the no-setup gate gets exercised on every reduced run.

---

### 5. 48-hour time-based auto-close

**What it does.** Any LONG/SHORT position OPEN for more than 48 hours that has not hit its target or stop is auto-closed at the current mark price with status `EXPIRED` and the appropriate `outcome_pct` recorded.

**Why it's #5.** The orphan SOL SHORT at unrealized −$1,369 / −74% is worth almost as much as the entire 4-week realized P&L. The current `check_and_close_positions` only closes on target/stop, not on time. A position with target far above price and stop far below price can sit OPEN indefinitely. This is pure hygiene with significant tail-risk reduction.

**Where.** Add `expire_stale_positions(symbol, current_price, max_hours=48)` to `tracker.py`. Call it from `check_and_close_positions` after target/stop checks. Add `EXPIRED` to `VALID_STATUSES`.

**Backfill.** Run a one-time cleanup to mark positions older than 48h as `EXPIRED` at current market — this clears the SOL zombie and any other stale rows.

**Concrete logic.**
```python
def expire_stale_positions(symbol: str, current_price: float, max_hours: int = 48):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_hours)).isoformat()
    rows = conn.execute("""
        SELECT id, recommendation, entry_price, position_size_usd
        FROM recommendations
        WHERE status='OPEN' AND symbol=? AND timestamp <= ?
    """, (symbol, cutoff)).fetchall()
    for row in rows:
        outcome_pct = compute_outcome(row['recommendation'], row['entry_price'], current_price)
        conn.execute("""
            UPDATE recommendations
            SET status='EXPIRED', close_price=?, outcome_pct=?, closed_at=?
            WHERE id=?
        """, (current_price, outcome_pct, datetime.now(timezone.utc).isoformat(), row['id']))
```

**Success criteria.** No OPEN positions older than 48h in the DB at any time. Realized P&L now reflects all decisions (no hidden unrealized drag).

**Effort.** Half day implementation plus one-time backfill run.

**Dependencies.** None.

---

### 6. Per-coin exposure cap tightened to 5%

**What it does.** Lower the existing exposure-guardrail thresholds. WARN at 3% same-direction notional (down from 10%); HARD CAP at 5% (down from 15%).

**Why it's #6.** The lookbacks repeatedly identified that 11 "independent" analysts piling into one direction acted as a single concentrated position, and that the 15% HARD CAP was too loose for an experimental LLM ensemble. ETH had 48 simultaneous SHORT calls last week — the existing guardrail caught the cascade only after most damage was done.

**Where.** `agents.py` (or wherever the §4.5 guardrail constants live in the local runner), and in the cowork SKILL.md. Constants: `EXPOSURE_WARN_PCT = 3.0`, `EXPOSURE_CAP_PCT = 5.0`.

**Success criteria.** Aggregate same-direction exposure on any single coin never exceeds 5% of $124K = $6,200 in the open book. Number of "HARD CAP triggered" events per week falls to near-zero (because the team self-throttles before reaching it).

**Effort.** 30 minutes.

**Dependencies.** None, but combines well with #7 below.

---

### 7. REX and ZEN default to WATCH unless they write an independent thesis

**What it does.** Both risk-manager personas now default their signal to WATCH. To upgrade to LONG or SHORT, they must produce a paragraph (>75 words, explicitly enforced by parser) that (a) does not reference any other analyst's call in this round, (b) cites at least one numeric data point with its actual value, and (c) is not based on book-management ("balancing the LONG side").

**Why it's #7.** The lookback nailed this exact failure: *"book-balancing SHORTs added real directional risk while framed as hedges, disguising true net exposure."* REX's win rate is decent but its thesis quality is suspect — it tends to lean with whichever direction the team is already in. ZEN's contrarian fades have lost money over 70 trades.

**Where.** `agents.py` REX and ZEN persona prompts. Add validation in the signal parser in `run_scheduled_analysis.py` and `main.py`: if recommendation is LONG/SHORT and the thesis section is <75 words OR contains references to other analyst names, downgrade to WATCH automatically and tag `rex-zen-thesis-rejected`.

**Success criteria.** REX and ZEN each emit LONG/SHORT in less than 30% of their per-coin opportunities (currently ~80%+). Win rate on their LONG/SHORT calls rises.

**Effort.** 1 day (prompt rewrite, parser validation, testing).

**Dependencies.** None.

---

### 8. RPL: drop from rotation OR cap position size at 0.1%

**What it does.** Either remove RPL from `DEFAULT_COINS` in `run_scheduled_analysis.py`, or add a per-symbol size override in `config.py` capping RPL position size at 0.1% ($124) regardless of analyst sizing.

**Why it's #8.** RPL has $1.78M daily volume across all venues. Combined open team notional of $43K LONG + $9K SHORT is a non-trivial fraction of daily turnover. The 0.5% size that's reasonable on BTC ($120B+ daily volume) is a different risk profile on RPL. The realized P&L on RPL is also small (-$322 over 28 days), so dropping it doesn't lose much.

**Recommended choice.** Drop RPL entirely. The team's edge on a $40M-cap LST token is unlikely to be its strongest, and the dollar impact of dropping it is minimal. Re-add later if a clear LST-specific thesis develops.

**Where.** `config.py` `DEFAULT_COINS` constant. Cowork skill `coins` list.

**Success criteria.** RPL trades stop. Team focus on BTC/ETH only.

**Effort.** 15 minutes.

**Dependencies.** None.

---

### 9. Confidence × calibration weighted sizing

**What it does.** Replace flat 0.5% sizing with a formula: `size_pct = base_pct × (confidence/10) × calibration_score`, where `calibration_score` is the 30-day rolling win rate for that (analyst, coin, confidence-bucket) tuple, defaulting to 1.0 when sample size is below 4.

**Why it's #9.** A conf=3 marginal call currently gets the same dollar exposure as a conf=8 conviction call. The calibration data is already computed in §4.5 of the cowork skill but isn't actually used for sizing — only for advisory text in the prompt. Wiring it into the math directly translates the team's own historical accuracy into capital allocation.

**Where.** Signal parser/persister in `run_scheduled_analysis.py`. After parsing the analyst's output but before insert, recompute `position_size_pct` and `position_size_usd` using the formula. Keep the analyst's stated size as a separate column (`stated_size_pct`) for audit.

**Success criteria.** High-confidence high-calibration calls get larger sizing; marginal calls get smaller sizing. Total notional in any direction respects the per-coin cap from item #6.

**Effort.** 1 day implementation; needs at least 2 weeks of data under items #1-#7 to tune.

**Dependencies.** Items #1, #2, #6 should be running for at least 2 weeks first so calibration data reflects the new regime.

---

### 10. Analyst panel consolidation OR aggressive simplification

**What it does.** Reduce 11 personas down to 4 distinct signal sources, each with non-overlapping data domains:
- **TAPE** — Technical + tape reading (folds ARIA, MARCUS, QUANT, parts of DELTA)
- **FLOW** — Derivatives + on-chain flows (folds VEGA, DELTA, CHAIN)
- **CONTEXT** — Macro + DeFi + regulatory (folds NOVA, DEFI, ATLAS)
- **RISK** — Single risk-manager seat with a hard veto power (folds REX + ZEN, retaining ZEN's numeric-trigger gate)

Alternative: simplify to 3 high-quality signals only, dropping personas that haven't earned their slot.

**Why it's #10.** All three external analyses (Grok, ChatGPT especially) and the original review converge that the 11-persona structure is mostly cosmetic — many personas read the same OHLC tape with different framings. ARIA + QUANT + MARCUS + DELTA likely have signal correlations >0.7. Consolidation would directly attack the false-diversification problem at its root.

**Why this is #10 and not higher.** It's a major rewrite. Items #1-#9 should produce 3-4 weeks of clean data first to *validate* whether consolidation is needed. If items #1-#9 alone close the HODL gap (item #3 measures this), consolidation may be unnecessary.

**Where.** `agents.py` (major rewrite of `ANALYST_CONFIGS`), `config.py` (`ANALYST_ORDER`), `dashboard.py` (color mapping).

**Decision rule.** Trigger this work *only if*: (a) after 4 weeks under items #1-#9, win rate has not crossed 45%, OR (b) HODL benchmark gap remains negative.

**Effort.** 1 week implementation, 2 weeks evaluation.

**Dependencies.** Items #1-#9 must be live for 4 weeks first to provide the decision data.

---

### 11. Guardrail historical backtest

**What it does.** Build `backtest_guardrails.py` that replays the last N days of market data through the guardrail logic in dry-run mode, producing a report of: which signals would have been blocked, which would have been downgraded, and the counterfactual P&L.

**Why it's #11.** The current guardrails (4/20 v1) are well-motivated by the lookbacks but have executed in production for only a handful of runs. Backtesting validates them — if they would have prevented the ETH cascade, ship with confidence; if they would have only caught some of it, layer on additional rules.

**Why this is #11 and not higher.** It's a validation tool, not an improvement. Items #1-#10 are the actual improvements. Backtest exists to *check* whether any of them are working.

**Where.** New script in repo root. Reads `recommendations.db`, replays guardrail logic against historical state, produces markdown report.

**Success criteria.** Report is generated and is honest. We learn whether v1 guardrails have demonstrated effect.

**Effort.** 2-3 days.

**Dependencies.** Useful any time, but most informative after items #1-#9 have produced a few weeks of new data tagged with `setup-gate-v1`, regime, and revised exposure caps.

---

## Execution roadmap

### Week 1 — Tier 1 (highest impact, lowest effort)
- **Day 1-2:** Items #4 (cadence) + #5 (48h time-stop) + #8 (RPL drop). Total ~1 day of work spread across two days.
- **Day 2-3:** Item #1 (no-setup gate). The biggest single win.
- **Day 3-4:** Item #3 (HODL benchmark). Establishes baseline before further changes.
- **Day 4-5:** Item #6 (5% exposure cap). Quick config change.

End of Week 1: System is dramatically pickier, has a measurable benchmark, and orphan positions are impossible.

### Week 2 — Tier 2 (high impact, more effort)
- **Day 6-8:** Item #2 (regime-aware prompting). The largest leverage on signal quality.
- **Day 9-10:** Item #7 (REX/ZEN default-WATCH). Prompt rewrites + parser validation.

End of Week 2: All structural fixes are live. Begin collecting clean data tagged `setup-gate-v1`, `regime-{X}`, `guardrails-v2` (cap at 5%).

### Week 3-4 — Observation and tuning
- Collect data. Run weekly lookback at end of week 3 against the new regime data only.
- **End of Week 4:** Item #11 (guardrail backtest) to validate v2 effectiveness.
- **End of Week 4 decision point:** Has win rate crossed 45%? Has HODL gap closed? If yes → continue and add Item #9 (calibration sizing). If no → trigger Item #10 (consolidation).

### Week 5+ — Tier 3 (data-dependent)
- Item #9 (calibration-weighted sizing) — needs the post-tier-1+2 data to tune.
- Item #10 (consolidation) — only if Week 4 decision triggers it.

---

## Success criteria — overall

After 4 weeks under the new regime:
- Win rate ≥ 45% (currently 37%)
- Realized P&L positive and stable, not heroic-BTC-saving-disastrous-ETH
- Aggregate same-direction per-coin exposure ≤ 5% at all times
- No OPEN positions older than 48 hours
- Cost ≤ $5/month on Sonnet
- HODL-benchmark gap improving week-over-week

If any of these fails after 4 weeks, escalate to Item #10 (consolidation/simplification) before doing additional tuning. Throwing more guardrails at a system that doesn't have edge is not a strategy.

---

## What's deliberately *not* in this plan

These were considered and excluded:

- **Adding more analysts or data sources.** The lookbacks identified information overload at marginal setups, not information shortage. More personas = more correlation, not more alpha.
- **Per-coin model tiering (Opus on BTC, Haiku on RPL).** Item #8 drops RPL entirely and item #4 cuts call volume. Cost is no longer the bottleneck; signal quality is.
- **Live trading deployment.** This is paper-trading and should remain so until at least 8 weeks of data show consistent positive HODL-benchmark gap.
- **External signal sources (Twitter sentiment, news APIs).** Same logic as more analysts — adds noise unless the underlying problem (false diversification) is fixed first.

---

_This document is a synthesis of `SYSTEM_REVIEW.md` plus three external LLM analyses. The ordering reflects estimated impact; effort estimates are approximate. Not financial advice. All work to be tagged in the database so before/after comparison is clean._
