# Lookback Recommendations — 2026-04-20

This document captures the code changes implemented on 2026-04-20 in response to
the weekly lookback post-mortem (`historical_analysis_BTC_20260420.md`,
`historical_analysis_ETH_20260420.md`, `historical_analysis_RPL_20260420.md`).

The 4/13–4/19 window produced the worst aggregate performance on record:

| Coin | Rows | LONG bias | LONG win rate | LONG avg |
|------|-----:|----------:|--------------:|---------:|
| BTC  | 247  | 96.4%     | 34.3%         | -0.04%   |
| ETH  | 263  | 93.5%     | **7.1%**      | **-2.26%** |
| RPL  | 111  | 91.0%     | 32.2%         | -0.31%   |

The lookback identified five structural problems that had been flagged in prior
weekly post-mortems without producing behavior change. This round of changes
moves the system from **advisory lessons** to **programmatic guardrails** that
execute inside the runner before the analyst sees any prior prompt.

---

## 1. Runtime guardrails (new module: `guardrails.py`)

A new module injects three pre-prompt context blocks into every analyst's
system prompt at the start of each scheduled run:

### 1.1 Exposure guard

`compute_exposure(symbol)` reads the open book on a coin and produces an
`ExposureSnapshot` with long/short counts and USD notional. If same-direction
notional on a coin exceeds:

- **10%** of the $124K portfolio → soft WARNING, analysts told to consider
  halving size or requiring a non-overlapping thesis.
- **15%** of the portfolio → HARD CAP, analysts told they **must** downgrade
  to WATCH or size ≤0.5%.

Addresses the repeated "9-10 analysts concurrent LONG = 18% of book disguised
as independent votes" pattern from the 4/20 lookback (BTC and ETH windows).

### 1.2 Cooldown guard

`find_recent_closed_losses(symbol, hours=12)` returns closed losing positions
on a coin within the last 12 hours. If any exist, the prompt tells the
analyst that reflex re-entry into the same direction/thesis requires either
(a) a new signal not present in the prior thesis, or (b) a WATCH downgrade.

Addresses the "re-enter same losing ETH LONG every 4h" pattern that drove the
7.1% win rate.

### 1.3 Confidence calibration

`get_confidence_calibration(analyst, symbol, days=30)` computes each
analyst's rolling conf→outcome history per coin. The guardrail injects lines
like:

```
conf=5: win_rate=45%  avg_outcome=+0.32%  n=35
conf=7: win_rate=18%  avg_outcome=-1.10%  n=28
```

directly into that analyst's system prompt alongside a rule: "if your conf=7
calls have a sub-25% win rate, a conf=7 today is likely overconfidence —
downgrade to conf=5 unless you can cite a signal absent from your prior
losing calls."

Addresses the inverted-confidence finding: high-conviction BTC/ETH/RPL calls
were the **worst** performers this week (conf=7 on ETH had a 5.6% win rate).

### Backward compatibility

`Analyst.analyze()` gains an optional `guardrail_block` parameter with a
default of `None`. When omitted, the analyst runs exactly as before — so the
interactive `main.py` session is unaffected, and existing tests still pass
untouched. Only `run_scheduled_analysis.py` opts into guardrails.

---

## 2. REX and ZEN prompt surgery (`agents.py`)

### 2.1 REX — now forced to abstain or challenge

REX's prompt now opens with an explicit accountability call-out: "the
2026-04-13..19 lookback showed you went LONG 28/28 on BTC and 27/1 on ETH —
a 0% challenge rate. That is trading the team's narrative, not risk
management."

REX is also required to emit a machine-parseable directive immediately before
his signal line:

```
EXPOSURE_BLOCK: YES     (book is over-extended; downstream MUST downgrade)
EXPOSURE_BLOCK: NO      (headroom exists; normal sizing applies)
```

`run_scheduled_analysis.py` parses this with `parse_rex_exposure_block()`
and, when YES, injects a matching note into ZEN's guardrail context before
ZEN runs. ZEN is therefore forced to respect REX's risk call.

### 2.2 ZEN — now gated by numeric triggers

ZEN's prompt was rewritten to require at least one of these numeric triggers
before publishing a LONG or SHORT signal:

- Funding rate > ±0.05% (directionally crowded)
- F&G index ≥ 75 or ≤ 25 (extremes)
- Put/Call ratio outside [0.6, 1.3]
- 7+ analysts already aligned (permits a fade, but still requires one
  numeric trigger from above)

If **no** numeric trigger fires, ZEN is required to publish WATCH or NEUTRAL.
This closes the "ZEN fires on vibes of crowdedness and loses -4% to -5%"
failure mode seen repeatedly in the 4/14–4/17 hours.

---

## 3. Parallel first-cohort (`run_scheduled_analysis.py`)

The single largest architectural change. The 11 analysts are now split:

```
FIRST_COHORT  = [ARIA, MARCUS, NOVA, VEGA, DELTA]      # parallel, blind to each other
SECOND_COHORT = [CHAIN, QUANT, DEFI, ATLAS, REX, ZEN]  # sequential, see cohort 1
```

- **Cohort 1** runs concurrently via `concurrent.futures.ThreadPoolExecutor`.
  Each analyst gets guardrails but no `prior_responses`. Their outputs are
  collected before any of them is shown to cohort 2.
- **Cohort 2** runs sequentially (same as before) because CHAIN/QUANT/DEFI/
  ATLAS/REX/ZEN are explicitly synthesizer roles — they *should* see the
  team's existing calls.
- Display order of cohort 1 is randomized per run via `random.shuffle`, so
  the same analyst doesn't sit at the top of the report every time.

This breaks the cascade where analysts 6–11 rubber-stamp the direction
established by analysts 1–5. An assertion at module import checks that the
cohort split exactly matches `config.ANALYST_ORDER` so a mismatch never
silently drops or double-runs an analyst.

REX runs second-to-last (position 10 of 11) in cohort 2 so his
EXPOSURE_BLOCK directive is available to inject into ZEN before ZEN runs.

---

## 4. Lookback v2 enhancements (`performance.py`)

`generate_lookback_report()` now pulls three new helpers into the Claude
synthesis prompt:

### 4.1 `compute_price_context(history)`

Summarizes the price regime over the lookback window using entry prices from
actual calls as a cheap proxy for OHLC. Labels the regime as steady uptrend,
steady downtrend, high-volatility chop, volatile uptrend, volatile
downtrend, or range-bound. Tells the Claude synthesizer *what the market
was actually doing* so "ETH dumped and longs lost" is distinguishable from
"ETH chopped and stops were too tight."

### 4.2 `compute_thesis_dispersion(history)`

Computes average pairwise Jaccard similarity between thesis text strings
within every same-hour same-direction cluster of 3+ analysts. Label:

- `≥ 0.40` → HIGH (groupthink — analysts are rephrasing one thesis)
- `0.25 – 0.40` → MODERATE (some overlap, but distinct lenses visible)
- `< 0.25` → LOW (theses are genuinely independent)

Gives the weekly post-mortem a *quantitative* groupthink number, not just a
narrative assertion.

### 4.3 `compute_lessons_attempted(symbol, days)`

Compares the current window's structural KPIs (LONG share, win rate,
high-conf share) against the window immediately before it. Surfaces whether
last week's prescribed lessons produced visible behavior change, or whether
the team is repeating the same mistake in a new week.

If LONG share drops and win rate rises week-over-week, the system has
evidence the lookback memory is being absorbed. If not, the next lookback
flags it directly as "lessons ignored."

---

## 5. Tests

Two new test files under `tests/`:

- `tests/test_guardrails.py` — 22 tests covering `compute_exposure`,
  `find_recent_closed_losses`, `get_confidence_calibration`,
  `build_guardrail_block`, and the REX directive parser.
- `tests/test_lookback_v2.py` — 10 tests covering `compute_price_context`,
  `compute_thesis_dispersion`, and `compute_lessons_attempted`.

Full pre-existing suite (`test_agents`, `test_tracker`, `test_performance`,
`test_round2`, `test_data_fetcher`, `test_indicators`, `test_coinbase`)
continues to pass with zero modifications — the `guardrail_block` parameter
is opt-in with a `None` default.

Run with:

```bash
pytest tests/ -v
```

Expected result: **154 passed**.

---

## 6. Mapping — each change to its source lookback finding

| Lookback finding (4/20) | Addressed by |
|---|---|
| 96%/94%/91% LONG bias on BTC/ETH/RPL | Exposure guard soft-caps same-direction pileups at 10%, hard-caps at 15% |
| REX 28/28 LONG on BTC, 27/1 on ETH | REX prompt rewrite + EXPOSURE_BLOCK directive |
| ZEN losing 5 of 7 SHORT attempts | ZEN prompt rewrite — numeric trigger required |
| Confidence inverted (conf=7 sub-25% win) | Calibration block injected into each analyst's prompt |
| 9-analyst same-direction clusters (ordering bias) | Parallel first-cohort breaks the cascade |
| "Same lessons recurring weekly" (closed loop broken) | Lookback v2 `compute_lessons_attempted` diffs week-over-week KPIs |
| Re-entry into losing ETH LONG every 4h | Cooldown guard flags closed losses within 12h |
| Narrative-only correlation warning | Lookback v2 `compute_thesis_dispersion` adds a number |
| Regime-blind analysts (trend assumption) | Lookback v2 `compute_price_context` labels regime |

---

## 7. How to verify on the next scheduled run

1. The next `crypto-4h-analysis` run will log, per coin, lines like:

   ```
   REX EXPOSURE_BLOCK: YES on ETH
   ```

   If the directive is missing, the runner emits a `degraded` tag
   `rex-missing-exposure-block-ETH` which surfaces on the dashboard.

2. When open BTC LONG notional is ≥$12,400 (10% of portfolio), every
   downstream analyst's system prompt will contain an "OPEN BOOK EXPOSURE —
   PRE-CALL CHECK" block with the exposure percentage and a rule tailored to
   whether it's a WARN or CAP situation.

3. The next `crypto-weekly-lookback` will include the three new v2 sections
   in the Claude prompt (PRICE CONTEXT, THESIS DISPERSION, LESSONS
   ATTEMPTED). You can grep `historical_analysis_*_20260426.md` for the
   string "THESIS DISPERSION" to confirm.

---

## 8. Rollback

Every change is additive and gated:

- `guardrails.py` is a new file — deleting it and reverting
  `run_scheduled_analysis.py` would fully restore sequential behavior.
- The `guardrail_block` parameter on `Analyst.analyze()` defaults to `None`;
  removing the runner's guardrail calls disables injection without touching
  any analyst.
- Lookback v2 helpers degrade to short "insufficient data" strings if the
  helpers themselves have bugs; they cannot break the Claude synthesis call
  since the helpers are invoked only to produce prompt strings.

To fully roll back:

```bash
git revert <commit-sha-of-this-pr>
```

No DB migrations are required — no schema changed. All data is written
through the existing `save_recommendation` and `save_lookback_memory`
paths.

---

## 9. Open follow-ups (not done this round)

- **Persona profitability tracking (quarterly).** A scheduled report that
  flags analysts who are structurally unprofitable across all coins (ATLAS
  at -1.84/-2.97/-6.24%) for rewrite or retirement. Deferred — requires
  more history than 7 days.
- **Analyst cohort re-randomization.** Currently cohort 1 is
  hardcoded to the first 5 seats in `ANALYST_ORDER`. A future change could
  shuffle *which* analysts are in cohort 1 each run, further weakening
  ordering bias.
- **Streamlit dashboard surfacing.** The dashboard does not yet render
  `EXPOSURE_BLOCK` state or same-direction exposure alerts. Adding a small
  "exposure pressure" widget on the History page would expose the guardrails
  to the human operator.
