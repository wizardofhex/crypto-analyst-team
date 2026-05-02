# Cowork Scheduled Tasks — full v2 stack

This document lists every Cowork scheduled task needed to run the v2 plan
end-to-end without a local Python cron. Set these up in the Cowork "Scheduled
Tasks" UI (one task per skill).

## Task 1 — LLM Team Analysis (existing, updated)

| Field | Value |
|-------|-------|
| Name | `crypto-12h-analysis-cowork` |
| Skill file | `SKILL.md` |
| Cron | `0 */12 * * *`  (every 12h, on the hour) |
| Cost | ~$0/run on Cowork (no API call — Cowork roleplays the team) |
| Coins | BTC, ETH (RPL dropped under v2) |
| Writes | `recommendations`, `analysis_reports` |
| Pushes | yes (fresh-clone) |

This is the v2 update to the existing `crypto-4h-analysis-cowork` task.
Update its cron from `0 */4 * * *` to `0 */12 * * *`.

## Task 2 — Deterministic Strategy B (new)

| Field | Value |
|-------|-------|
| Name | `crypto-deterministic-strategy-cowork` |
| Skill file | `SKILL_deterministic.md` |
| Cron | `5 */12 * * *`  (5 minutes after Task 1) |
| Cost | ~$0/run (no LLM call — pure rule evaluation) |
| Coins | BTC, ETH |
| Writes | `recommendations_deterministic` |
| Pushes | yes (fresh-clone) |

Runs the pre-registered rule-based strategy. Five-minute offset from Task 1
prevents git-push collisions. Skip-if-fresh threshold: 6h.

## Task 3 — RPL Hold Monitor (new)

| Field | Value |
|-------|-------|
| Name | `crypto-rpl-hold-monitor-cowork` |
| Skill file | `SKILL_rpl_hold.md` |
| Cron | `0 12 * * 0`  (Sundays at noon UTC) |
| Cost | ~$0/run on Cowork |
| Holdings | RPL @ 10,000 units |
| Writes | `hold_recommendations`, `analysis_reports` |
| Pushes | yes (fresh-clone) |

Weekly long-term hold monitor. Runs the 7-analyst subset
(ARIA/NOVA/CHAIN/QUANT/DEFI/ATLAS/REX) in HOLD mode. Recommends
HOLD/ADD/TRIM/EXIT with target units and price levels. Skip-if-fresh
threshold: 6 days.

## Task 4 — Pre-Mortem Hypothesis Tests (new)

| Field | Value |
|-------|-------|
| Name | `crypto-premortem-tests-cowork` |
| Skill file | `SKILL_premortem.md` |
| Cron | `30 23 * * 0`  (Sundays 23:30 UTC, end of week) |
| Cost | ~$0/run (no LLM call — SQL only) |
| Writes | `hypothesis_tests` |
| Pushes | yes (fresh-clone) |

Weekly evaluator for the four pre-mortem hypotheses (H1-H4). Status appears
on the Strategy Comparison dashboard page.

## Cron schedule visualization

```
Hour:   00  04  08  12  16  20
Mon-Sat 12   .   .  12   .   .   <- Task 1 (LLM team, every 12h)
        12   .   .  12   .   .   <- Task 2 (Deterministic, +5m offset)

Sunday  ↑ same as above + 12:00 UTC RPL Hold Monitor (Task 3)
                            + 23:30 UTC Pre-Mortem Tests (Task 4)
```

## What this gets you

**Daily:** 2 runs of LLM team + 2 runs of deterministic strategy on BTC/ETH.
Both write to the same DB, both push, Streamlit redeploys after each push.

**Weekly:** RPL hold-monitor recommendation + the four pre-mortem hypothesis
test results. Both surface on the dashboard.

**No local Python required.** The only thing on the user's machine is
clicking "view dashboard" in a browser. All analysis, all DB writes, all
GitHub pushes happen in Cowork.

## Things that still need a local component

- **Streamlit dashboard server** — runs on Streamlit Cloud (free tier),
  auto-deploys from the GitHub repo. Not Cowork-hosted, but doesn't need to
  be — it's a public web app.
- **`.env` with `ANTHROPIC_API_KEY`** — only required if you want to ALSO run
  the local Python `run_scheduled_analysis.py` as a redundant path. The
  Cowork SKILLs do not require it.
- **`gh auth setup-git`** — only required if Cowork's git push auth ever
  fails over and you fall back to local push.

## Health-check script

After setting up all four tasks, verify they're connected to the right DB
by checking the schema:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('recommendations.db')
print('tables:', [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])
print('hold_positions:', conn.execute('SELECT * FROM hold_positions').fetchall())
"
```

Expected output:
```
tables: ['recommendations', 'analyst_stats', 'lookback_memory', 'hold_positions',
         'hold_recommendations', 'analysis_reports', 'hypothesis_tests',
         'recommendations_deterministic', 'sqlite_sequence']
hold_positions: [(1, 'RPL', 10000.0, None, None, '...notes...', '...timestamp...')]
```
