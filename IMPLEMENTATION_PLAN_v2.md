# Crypto Analyst Team — Implementation Plan v2

**Date:** 2026-05-02
**Supersedes:** `IMPLEMENTATION_PLAN.md`
**Driving change:** Three independent adversarial reviews (Gemini, Grok, ChatGPT under the v2 prompt) converged on a single finding: P(LLM ensemble has positive expectancy at 1-year horizon) ≈ 9% across all three. Two of three independently proposed a deterministic-baseline parallel track. This plan treats the LLM-ensemble premise as a falsifiable hypothesis rather than the system's foundation.

---

## What changed and why

The v1 plan optimized the LLM team's behavior on the assumption that better filtering, prompting, and sizing could produce edge. The v2 reviews pointed out that this is unfalsifiable as written: if the team underperforms after 8 weeks, the v1 plan has no clean way to distinguish "the guardrails were wrong" from "the underlying signal generator never had edge."

This v2 plan rebuilds around three principles:

**1. Horse race, not optimization.** Three strategies run in parallel against the same data feed: HODL benchmark, a pre-registered deterministic rule-based strategy, and the LLM team with all its guardrails. All three measured identically. The data at week 4 picks the winner.

**2. Pre-registered hypotheses.** Each of the three reviewers' specific failure-mode predictions is converted into a numerical test that runs automatically. We can no longer fail silently — failure modes are instrumented up front.

**3. Decision rules baked in.** The week 4 decision tree is specified now, before any data exists, with concrete trigger conditions. If the LLM team loses to either alternative, the response isn't "tune more guardrails" — it's a specific, pre-committed pivot.

The five Tier-1 items from v1 (no-setup gate, cadence cut, 48h time-stop, exposure cap tightening, RPL drop) survive — every reviewer endorsed them. The high-effort items from v1 (regime-aware prompting, calibration-weighted sizing, panel consolidation) are now conditional on Phase 3 outcomes rather than committed up front.

---

## The three competing strategies

### Strategy A — HODL Benchmark
Equal-weight 1/3 BTC + 1/3 ETH + 1/3 RPL allocation anchored at the database start date (2026-04-04). Marked daily. No rebalancing. This is the no-skill baseline — if the team can't beat this, the team has no alpha.

### Strategy B — Deterministic Rules (pre-registered)
A hard-coded rule-based strategy using the same `indicators.py` data the LLMs see. Rules are committed below and **must not be tuned during the test window** — that's the test.

**Entry rules — Trend Pullback (LONG):**
- Price > EMA-200 (uptrend confirmed) AND
- RSI(14) between 40 and 55 (pullback within uptrend) AND
- ATR(14) ≥ 1.0× its 20-bar mean (vol participating, not flat) AND
- Funding rate ≤ 0.05% (not crowded long)

**Entry rules — Trend Pullback (SHORT):** mirror image.

**Entry rules — Capitulation (LONG):**
- BB%B < 5 (price at/below lower band) AND
- Volume > 3× volume_sma_20 AND
- Last candle bullish (close > open)

**Entry rules — Blow-off (SHORT):**
- BB%B > 95 (price at/above upper band) AND
- Volume > 3× volume_sma_20 AND
- Last candle bearish (close < open)

**Exits:**
- Stop: entry ± 1.5 × ATR(14)
- Target: entry ± 3 × ATR(14) (R:R = 1:2)
- Time-stop: 48 hours

**Sizing:** Flat 1% of $124K = $1,240 per position. Max 2 concurrent same-direction positions per coin.

**Cadence:** Evaluated on every scheduled run (12h cadence, same as LLM team).

This rule set is deliberately simple, uses indicators the team already computes, and codifies the two patterns the lookbacks identified as the team's actual edge (capitulation/blow-off) plus the standard trend-pullback. It is intentionally not optimized.

### Strategy C — LLM Team
The 11-persona ensemble with all v1 guardrails plus the v2 additions in this plan. Same 12h cadence. Same time-stops. Same exposure caps.

---

## Pre-registered hypotheses (from the v2 reviews)

These are the failure mechanisms the reviewers predicted. Each is now an automated test the dashboard reports weekly. Falsification thresholds are committed up front.

### H1 — "Regime-induced paralysis" (Gemini)
**Prediction:** When Item #6 (regime-aware prompting) is live, analysts will emit WATCH/NEUTRAL at high rates during RANGE_BOUND_MID and LOW_VOL_CONTRACTION regimes. The system will filter losses but also filter the breakout moves where money is made.

**Test:** Compute (a) the WATCH-rate per regime label, (b) the realized 24h price move on coins where the team emitted WATCH while regime was RANGE_BOUND_MID/LOW_VOL_CONTRACTION.

**H1 confirmed if:** WATCH-rate > 70% in those regimes AND average post-WATCH 24h move > 1.5× ATR. This means the team is sleeping through tradeable moves.

### H2 — "Coarse classifier collapse" (Grok)
**Prediction:** The regime classifier in Item #6 will assign RANGE_BOUND_MID to most periods, making the regime label uninformative.

**Test:** Distribution of regime labels assigned over the 4-week test window.

**H2 confirmed if:** any single regime label is assigned to > 60% of runs. This means the classifier isn't actually classifying.

### H3 — "Calibration on noise" (ChatGPT)
**Prediction:** Calibration-weighted sizing (Item #11 in this plan, deferred from Phase 3) will fit noise because the 30-day per-(analyst, coin, confidence-bucket) sample sizes are too small. Weights will swing wildly week-over-week.

**Test:** Compute the week-over-week absolute change in each calibration weight, averaged across all (analyst, coin, conf-bucket) tuples with n ≥ 4.

**H3 confirmed if:** average week-over-week swing > 0.20 (i.e., calibration scores changing by 20+ percentage points weekly). This means we're calibrating on randomness.

### H4 — "Tier 1 silently broken" (all three, average 59% probability)
**Prediction:** At least one Tier 1 item will be in production but not actually working — either due to a bug, a misaligned threshold, or a downstream change masking its effect.

**Test:** End-of-week-2 sanity audit. Each Tier 1 item gets a one-line "is it working?" check:
- #1 (no-setup gate): % of runs that skipped the analyst loop. Target: 40-70%. Outside this range = misconfigured.
- #2 (cadence): exactly 2 scheduled runs/day visible in the heartbeat log.
- #3 (48h time-stop): zero OPEN positions older than 48h in `recommendations`.
- #4 (5% cap): no per-coin same-direction notional > $6,200 in the open book.
- #5 (RPL drop): zero new RPL signals after deployment.

**H4 confirmed if:** any of the five fails its sanity check at end of week 2.

---

## Phase 0 — Instrumentation (Week 1, parallel with Phase 1)

### Item #0 — Deterministic Baseline Strategy
**What.** Implement Strategy B above as a separate runner: `run_deterministic_strategy.py`. It evaluates the rule set on the same data feed the LLM team uses, writes signals to a new table `recommendations_deterministic` (mirror schema of `recommendations`), and is invoked on the same 12h cron after the LLM team finishes.

**Why.** Without this, the project has no way to distinguish "the LLM team has weak edge" from "the market regime itself is untradeable at this timeframe." This is the single most important addition. Both Grok and ChatGPT identified it independently.

**Where.** New file `run_deterministic_strategy.py` at repo root. Reuses `data_fetcher.py`, `indicators.py`, `tracker.py` (with table parameter). New table created via `tracker.init_db()`.

**Success criteria.** Strategy B is running on every 12h cycle, producing signals to its own table, with full lifecycle management (entry, stop, target, time-stop) identical to the LLM team's.

**Effort.** 2 days. The rule set is fully specified — implementation is mechanical.

**Dependencies.** None. Can ship independently of any LLM-team change.

### Item #0.5 — Multi-Strategy Comparison Dashboard
**What.** Replace the existing dashboard's primary view with a three-curve performance comparison: HODL, Deterministic, LLM Team. Anchor date 2026-04-04. Daily mark-to-market on each. Plus six secondary panels:

1. Equity curves (three lines, $124K starting capital each)
2. Cumulative win rate over time (three lines)
3. Trade count per week (three bars per week)
4. Average trade outcome % (three lines)
5. Per-regime performance heatmap (LLM team only — reads regime tags)
6. Pre-mortem hypothesis dashboard (H1, H2, H3, H4 status with green/yellow/red)

**Why.** Without this view, no honest comparison can be made and no decision rules can fire. This is the measurement layer the rest of the plan depends on.

**Where.** `dashboard.py` — major rewrite of the homepage. Add `pages/2_strategy_comparison.py` if Streamlit's multi-page is preferred.

**Success criteria.** All three curves render. The hypothesis dashboard correctly evaluates H1-H4 conditions weekly. Outperformance vs HODL is calculable for each strategy at any point in time.

**Effort.** 2 days.

**Dependencies.** Item #0 must be writing data; HODL benchmark code from v1 Item #3 must exist.

### Item #0.6 — Pre-Mortem Hypothesis Test Harness
**What.** A weekly automated job that evaluates H1-H4 against the database state and writes a one-row summary per hypothesis to a new `hypothesis_tests` table. The dashboard's hypothesis panel reads this table.

**Why.** Hypotheses that aren't automatically tested are hopes. Each prediction from the v2 reviews becomes a yes/no result we can act on.

**Where.** New file `pre_mortem_tests.py`. Run as part of the existing `run_weekly_lookback.py` schedule.

**Success criteria.** End of every week the four hypotheses have committed numerical results stored in the DB.

**Effort.** 1 day.

**Dependencies.** Item #6 must be live before H1 and H2 can be evaluated.

---

## Phase 1 — Stop the Bleeding (Week 1, parallel with Phase 0)

These five items are the universal-consensus changes from both review rounds. They ship in week 1 regardless of any other plan element.

### Item #1 — No-Setup Precondition Gate (LLM team only)
**What.** Same as v1 item #1 — skip the LLM analyst loop on a coin if no setup conditions are met. Triggers: ATR ratio > 1.3×, near key level (1 ATR of EMA-200, 7d high/low), funding extreme, F&G ≤ 25 or ≥ 75, 24h move > 2 ATR. Tagged `setup-gate-v1`.

**Important:** does NOT apply to Strategy B (deterministic). Strategy B has its own entry rules; the no-setup gate is specifically a filter for the LLM team's tendency to find marginal trades in chop.

**Where.** Function in `data_fetcher.py` or new `regime_filter.py`. Called from `run_scheduled_analysis.py` per coin before the analyst loop.

**Success criteria.** 40-70% of LLM team runs skip the analyst loop (matches H4 threshold).

**Effort.** 1-2 days.

**Dependencies.** None.

### Item #2 — Cadence 4h → 12h
**What.** Change scheduled-tasks cron from `0 */4 * * *` to `0 */12 * * *`. Update Cowork fallback skip-if-fresh from 2700s → 21600s. Update `CLAUDE.md` cost estimates.

**Effort.** 1 hour.

**Dependencies.** None.

### Item #3 — 48-Hour Auto-Close (all strategies)
**What.** Add `expire_stale_positions(symbol, current_price, max_hours=48)` to `tracker.py`. Call from `check_and_close_positions`. Status flips to `EXPIRED`. Backfill once on deploy to clear the SOL zombie.

**Important:** applies to BOTH `recommendations` and `recommendations_deterministic` tables. Same hygiene rule for all strategies for clean comparison.

**Effort.** Half day.

**Dependencies.** None for v1 functionality; Item #0 should exist before backfill so the deterministic table is also cleaned.

### Item #4 — Tighten Exposure Cap to 5% (LLM team only)
**What.** Lower thresholds in §4.5 of cowork skill / equivalent in `agents.py` to: WARN at 3%, HARD CAP at 5%.

**Important:** does NOT apply to Strategy B — it has its own per-position $1,240 sizing with a max-2-concurrent rule that achieves the same goal differently. Forcing the same exposure logic on a deterministic strategy distorts the comparison.

**Effort.** 30 minutes.

**Dependencies.** None.

### Item #5 — Drop RPL
**What.** Remove RPL from `DEFAULT_COINS`. Cowork fallback `coins` list updated to `BTC, ETH` only. Strategy B also drops RPL.

**Effort.** 15 minutes.

**Dependencies.** None.

---

## Phase 2 — Test the LLM Premise (Week 2-3)

These are the items the v2 reviews specifically warned about. They ship, but with H1 and H2 instrumentation actively monitoring for the predicted failures.

### Item #6 — Regime-Aware Prompting (with H1/H2 monitoring)
**What.** Six-state regime classifier in `indicators.py` returning one of: `STRONG_UPTREND`, `STRONG_DOWNTREND`, `HIGH_VOL_EXPANSION`, `LOW_VOL_CONTRACTION`, `RANGE_BOUND_MID`, `BREAKOUT_EXHAUSTION`. Inject into LLM prompts. Tag every signal with the regime it was generated under.

**H1 monitoring:** Track WATCH-rate per regime. If H1 confirms (WATCH-rate > 70% in low-vol regimes AND average post-WATCH 24h move > 1.5× ATR), Item #6 will be loosened at week 3 — specifically, the "default to WATCH/NEUTRAL unless exceptional confirmation" instruction will be replaced with "weight your skepticism by regime but do not refuse to take a position when the data supports it."

**H2 monitoring:** Track regime label distribution. If H2 confirms (any single label > 60% of runs), the classifier thresholds are recomputed at week 3.

**Why.** Two of three reviewers predicted this would fail in specific ways. We ship it anyway because the lookbacks identified mid-range trend-continuation as the worst trade pattern, and a regime-aware prompt is the obvious fix. But we ship it with predictions registered, not faith.

**Where.** `indicators.py` (classifier). `agents.py` (prompt construction). New SQL column or tag for regime per row.

**Success criteria.** Items #6 passes H1 and H2 at week 3. If either fails, the corresponding adjustment ships.

**Effort.** 2-3 days for the implementation, plus the H1/H2 dashboards (covered by Item #0.6).

**Dependencies.** Item #0.6 must exist to monitor.

### Item #7 — REX/ZEN Default-WATCH (independent thesis required)
**What.** REX and ZEN persona prompts modified to default WATCH. Upgrade requires a thesis paragraph >75 words containing at least one cited numeric data value, with no references to other analyst names. Parser auto-downgrades to WATCH if these conditions fail and tags the row `rex-zen-thesis-rejected`.

**Why.** The lookbacks are explicit: book-balancing was being framed as a thesis. This is the cleanest fix. Universal consensus across all reviewers.

**Where.** `agents.py` (REX_PROMPT, ZEN_PROMPT). Parser validation in `run_scheduled_analysis.py` and `main.py`.

**Success criteria.** REX and ZEN emit LONG/SHORT in <30% of opportunities (down from ~80%+). Win rate on the LONG/SHORT calls they DO make rises by ≥5pp vs the pre-change baseline.

**Effort.** 1 day.

**Dependencies.** None.

---

## Phase 3 — Decision Point (Week 4)

This is the central decision the entire plan is structured around.

### Item #8 — Multi-Strategy Decision Gate (Week 4 review)
**What.** At end of week 4, a structured comparison runs:

| Metric | HODL | Deterministic | LLM Team |
|--------|------|---------------|----------|
| 4-week return % | A% | B% | C% |
| Realized win rate | n/a | B_wr% | C_wr% |
| Sharpe (daily) | A_sh | B_sh | C_sh |
| Max drawdown | A_dd | B_dd | C_dd |
| Trades per week | n/a | B_n | C_n |

**Decision rules (committed up front, do not adjust at week 4):**

- **Branch A — LLM Team Wins.** LLM Team return > Deterministic return AND LLM Team return > HODL return − 3pp (allow some HODL underperformance from active hedging). **Action:** Continue. Add Item #11 (calibration sizing) for Phase 4. The premise is validated.

- **Branch B — Deterministic Wins.** Deterministic return > LLM Team return by ≥ 5pp. **Action:** Pivot. The 11-persona panel becomes a *supervisory layer* over deterministic signals — i.e., the rule-based engine emits trades, and the LLM panel can only veto (downgrade to WATCH), never originate. Item #10 (panel consolidation) is reframed as a 4-cluster veto council, not a signal generator. The user has 4 weeks of clean data to confirm this works.

- **Branch C — HODL Wins.** Both Deterministic AND LLM Team underperform HODL by > 5pp. **Action:** Halt active trading. The market regime over the test window doesn't have an exploitable edge at this timeframe with these tools. Switch to a 12-week observation window where all three strategies continue running but no new code is written. If the gap closes, resume; if not, the project has answered its core question and can either pivot fundamentally (different timeframe, different assets) or close.

- **Branch D — Tie / unclear.** All three within 3pp of each other. **Action:** Extend test window 4 more weeks. Do not add complexity. Do not adjust strategies. Let the larger sample resolve it.

**Why.** Without committed decision rules, the week 4 review will look like every prior review: more guardrails, more tuning, no answer. The reviewers' core critique was that the v1 plan was unfalsifiable. This makes it falsifiable.

**Where.** Decision document drafted now (in this plan), executed at end of week 4.

**Success criteria.** A branch is selected. No "let's see how week 5 goes" punt allowed unless Branch D triggers.

**Effort.** 1 day (the review itself).

**Dependencies.** All Phase 0 / 1 / 2 items complete and at least 4 weeks of data.

---

## Phase 4 — Execute the Verdict (Week 5+)

Conditional on the Phase 3 branch chosen.

### Item #9 (conditional, Branch A) — Calibration-Weighted Sizing
**Same as v1 item #9, but only ships if Phase 3 selected Branch A.** H3 (calibration-on-noise hypothesis) must be passing — calibration scores stable week-over-week. If H3 confirms, this item is skipped and replaced with simpler confidence-only weighting.

### Item #10 (conditional, Branch B) — LLM-as-Supervisor Architecture
**Major rewrite, only ships if Phase 3 selected Branch B.** Strategy B (deterministic) becomes the primary signal generator. The 11-persona LLM team is consolidated to a 4-cluster veto council (TAPE, FLOW, CONTEXT, RISK). Each cluster can downgrade a deterministic signal to WATCH but cannot originate. ZEN's numeric-trigger gate becomes the cluster veto rule.

### Item #11 (always) — Guardrail Historical Backtest
**Same as v1 item #11.** Replay last 6+ weeks of market data through current guardrail logic in dry-run mode. Validate which guardrails actually move the needle. Ships in week 6 regardless of branch.

---

## Execution roadmap

### Week 1 — Phase 0 + Phase 1 in parallel
- **Day 1-2:** Items #2 (cadence), #3 (time-stop), #4 (cap), #5 (RPL drop). 1 person-day total.
- **Day 1-3:** Item #0 (deterministic strategy). Most important new work.
- **Day 2-3:** Item #1 (no-setup gate).
- **Day 3-4:** Item #0.5 (dashboard rewrite).
- **Day 4-5:** Item #0.6 (hypothesis test harness).

End of Week 1: All three strategies running on the same 12h cadence. Dashboard shows three curves. Hypothesis tests stubbed.

### Week 2 — Phase 2
- **Day 6-8:** Item #6 (regime-aware prompting + H1/H2 instrumentation).
- **Day 9-10:** Item #7 (REX/ZEN default-WATCH).
- **End of week 2:** H4 sanity audit. Each Tier 1 item verified working as designed.

### Week 3 — Observation
- All strategies running. Hypothesis tests producing weekly results.
- If H1 or H2 confirmed, week 3 includes the loosening adjustments to Item #6.

### Week 4 — Decision
- **Day 27:** Pull the comparison numbers.
- **Day 28:** Phase 3 review. Select Branch A, B, C, or D. Document the decision.

### Week 5+ — Verdict execution
- Per branch.

---

## Honest disclosures

This plan accepts that the project may be wrong. The committed structure means:

- If Branch B fires, ~8 weeks of work optimizing the LLM team has produced an answer of "it was the wrong tool." That's a legitimate outcome and the cheapest way to learn it.
- If Branch C fires, the project's core thesis (LLM ensembles can produce trading edge) was wrong, AND deterministic rules also can't generate edge in this regime. The project pivots fundamentally or closes.
- The reviewers placed P(Branch C) ≈ 30-40% combined. That's not a small number. The plan must be willing to act on it.

The v1 plan implicitly assumed Branch A. The v2 plan assigns no prior — the data picks.

---

## Overall success criteria

**Week 4:**
- A Phase 3 branch is selected (A, B, C, or D), not deferred.
- All four pre-mortem hypotheses (H1-H4) have committed numerical results.
- The three-strategy dashboard is the primary view people consult.

**Week 8:**
- The project has a confident answer to "does the LLM-ensemble approach produce trading edge in this regime?" — yes, no, or "needs longer sample."
- The deterministic baseline has at least 8 weeks of data, providing a permanent benchmark for any future iteration.
- HODL gap is closing OR the project has explicitly chosen to stop trying to beat HODL.

**Year 1 (aspirational):**
- The project knows whether LLM signal generation has any place in its architecture, with evidence.
- Capital deployed (paper or live) is in whichever strategy actually demonstrated edge over the test windows.

---

## What's deliberately NOT in this plan

- **Adding more analysts or data sources.** The reviewers' core critique was *false diversification*; adding personas makes it worse.
- **Live trading.** All three strategies remain paper-traded until at least 8 weeks of post-Phase-3 data exist showing positive expectancy.
- **External data feeds (Twitter, news APIs).** Same noise problem as more personas.
- **Calibration-weighted sizing in Phase 1 or Phase 2.** Deferred to Phase 4 specifically because H3 predicts it will calibrate on noise. We test H3 first.
- **Per-coin model tiering.** Cadence reduction handles the cost concern; signal quality is the bottleneck.

---

## Acknowledgments

This plan integrates direct contributions from:
- **Grok (v2 review):** the deterministic-baseline-first proposal as Item #0.
- **ChatGPT (v2 review):** the deterministic-as-validator framing that shaped Branch B.
- **Gemini (v2 review):** the regime-induced-paralysis prediction that became H1.

All three review rounds are preserved in the workspace folder as `gemini_*.md`, `grok_*.md`, `chatgpt_*.md` for the record. The v1 plan is preserved as `IMPLEMENTATION_PLAN.md`.

---

_This document is a synthesis of system review, three external first-pass analyses, and three structured adversarial reviews. Not financial advice. All work to remain in paper-trading mode through at least Phase 4. Decision rules in Phase 3 are committed in advance and must not be adjusted at evaluation time — that's what makes them decision rules._
