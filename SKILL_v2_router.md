---
name: crypto-v2-router-cowork
description: Single-task v2 router for Cowork. Runs all four v2 jobs in sequence (LLM team analysis, deterministic Strategy B, RPL hold monitor weekly, pre-mortem hypothesis tests weekly). Each sub-job has its own skip-if-fresh logic so the right cadence is observed regardless of the cron firing the router. Use this when you cannot create separate scheduled tasks for each skill.
---

# v2 Router

This skill is the all-in-one fallback for Cowork environments where you cannot
create one scheduled task per skill. Point your single existing scheduled task
at this file; whatever cron it fires on (every hour, every 4h, every 12h —
doesn't matter), the router will:

1. Always: clean stale git locks
2. Hourly-or-faster cron tolerated: each sub-job has its own skip-if-fresh
3. Run LLM-team analysis if last team signal > 11h old (effective 12h cadence)
4. Run deterministic Strategy B if last B signal > 11h old (effective 12h)
5. Run RPL hold monitor if last hold rec > 6 days old (effective weekly)
6. Run pre-mortem hypothesis tests if no rows yet for the current ISO week
7. Push the DB once at the end if anything changed

**One push per router run, not four.** That's important: it minimizes git
contention and keeps the GitHub commit log clean.

## 0. WORKSPACE SETUP

```bash
WORKSPACE=$(ls -d /sessions/*/mnt/crypto_analyst_team 2>/dev/null | head -1)
[ -z "$WORKSPACE" ] && { echo "ERROR: workspace not found"; exit 1; }
cd "$WORKSPACE"

for f in $(find .git -name '*.lock' 2>/dev/null); do
  mv "$f" "${f}.stale.$(date +%s)" 2>/dev/null || true
done

RUN_ID=$(date -u +%Y%m%d_%H%MZ)
SCRATCH=/tmp/v2router_$RUN_ID
mkdir -p $SCRATCH
echo "router run: $RUN_ID  |  workspace: $WORKSPACE"
```

## 1. CHECK WHAT NEEDS TO RUN

```bash
python3 << 'PY'
import sqlite3, json
from datetime import datetime, timezone
from pathlib import Path

now = datetime.now(timezone.utc)
iso_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"

conn = sqlite3.connect('recommendations.db', timeout=5)
conn.execute('PRAGMA journal_mode=WAL')

def age_seconds(table_or_query):
    """Return seconds since the most-recent timestamp in the given query."""
    try:
        c = conn.cursor()
        c.execute(table_or_query)
        r = c.fetchone()
        return r[0] if r and r[0] is not None else 999999
    except Exception:
        return 999999

def table_exists(name):
    return conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (name,)
    ).fetchone()[0] > 0

state = {
    "team_age_s": age_seconds(
        "SELECT strftime('%s','now') - strftime('%s', MAX(timestamp)) FROM recommendations"
    ),
    "det_age_s": (age_seconds(
        "SELECT strftime('%s','now') - strftime('%s', MAX(timestamp)) FROM recommendations_deterministic"
    ) if table_exists("recommendations_deterministic") else 999999),
    "hold_age_s": (age_seconds(
        "SELECT strftime('%s','now') - strftime('%s', MAX(timestamp)) FROM hold_recommendations WHERE symbol='RPL'"
    ) if table_exists("hold_recommendations") else 999999),
    "premortem_done_this_week": False,
}

if table_exists("hypothesis_tests"):
    n = conn.execute(
        "SELECT COUNT(*) FROM hypothesis_tests WHERE week_id = ?", (iso_week,)
    ).fetchone()[0]
    state["premortem_done_this_week"] = n >= 4

# Decision flags
state["run_team"] = state["team_age_s"] >= 39600       # 11h
state["run_det"] = state["det_age_s"] >= 39600         # 11h
state["run_hold"] = state["hold_age_s"] >= 518400      # 6d
state["run_premortem"] = not state["premortem_done_this_week"]

# Sunday-only gate for hold (avoid weekday RPL noise) — comment out if you want any-day
if now.weekday() != 6:  # 6 = Sunday
    state["run_hold"] = False

import os
Path("/tmp/v2router_state.json").write_text(json.dumps(state, indent=2))
print(json.dumps(state, indent=2))
PY

source <(python3 -c "
import json
s = json.load(open('/tmp/v2router_state.json'))
for k, v in s.items():
    if isinstance(v, bool):
        print(f'export {k.upper()}={1 if v else 0}')
")
echo "Decisions: TEAM=$RUN_TEAM DET=$RUN_DET HOLD=$RUN_HOLD PREMORTEM=$RUN_PREMORTEM"
```

## 2. SUB-JOB EXECUTION

For each flag set, execute the corresponding sub-skill INLINE. Don't
re-fetch the same market data four times — fetch once, share.

### 2a. LLM team analysis

```bash
if [ "$RUN_TEAM" = "1" ]; then
  echo "=== Running LLM team analysis ==="
  # Read SKILL.md sections 2-9 and execute them. The skill is already
  # written to be self-contained; the only change for the router context
  # is that we DON'T push at the end of this section — the router pushes
  # once at the very end (§3).
  #
  # In practice: roleplay the 11 analysts on BTC and ETH per SKILL.md's
  # cohort + guardrail structure, parse signals, write to DB, save the
  # full markdown report to analysis_reports.
  echo "(See SKILL.md sections 3-9 for the full procedure)"
else
  echo "Skipping LLM team — last signal too recent."
fi
```

### 2b. Deterministic Strategy B

```bash
if [ "$RUN_DET" = "1" ]; then
  echo "=== Running deterministic Strategy B ==="
  python3 run_deterministic_strategy.py BTC ETH 2>&1 | tail -10
else
  echo "Skipping Strategy B — last signal too recent."
fi
```

### 2c. RPL hold monitor (weekly)

```bash
if [ "$RUN_HOLD" = "1" ]; then
  echo "=== Running RPL hold monitor ==="
  if [ -f run_hold_monitor.py ] && [ -n "$ANTHROPIC_API_KEY" ]; then
    python3 run_hold_monitor.py RPL 2>&1 | tail -20
  else
    echo "(See SKILL_rpl_hold.md sections 3-4 for the inline 7-analyst roleplay procedure)"
  fi
else
  echo "Skipping RPL hold — already ran this week or not Sunday."
fi
```

### 2d. Pre-mortem hypothesis tests (weekly)

```bash
if [ "$RUN_PREMORTEM" = "1" ]; then
  echo "=== Running pre-mortem hypothesis tests ==="
  python3 pre_mortem_tests.py 2>&1 | tail -15
else
  echo "Skipping pre-mortem — already evaluated for this ISO week."
fi
```

## 3. PUSH ONCE AT THE END

```bash
if [ "$RUN_TEAM" = "1" ] || [ "$RUN_DET" = "1" ] || [ "$RUN_HOLD" = "1" ] || [ "$RUN_PREMORTEM" = "1" ]; then
  REMOTE=$(git config --get remote.origin.url)
  rm -rf "$SCRATCH/push" 2>/dev/null
  git clone --depth 2 "$REMOTE" "$SCRATCH/push" 2>&1 | tail -2
  cp recommendations.db "$SCRATCH/push/recommendations.db"
  cd "$SCRATCH/push"
  git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork v2 Router" \
      add recommendations.db
  if git diff --cached --quiet; then
    echo "No DB changes after sub-jobs; nothing to push."
  else
    JOBS=""
    [ "$RUN_TEAM" = "1" ] && JOBS="$JOBS team"
    [ "$RUN_DET" = "1" ] && JOBS="$JOBS det"
    [ "$RUN_HOLD" = "1" ] && JOBS="$JOBS hold"
    [ "$RUN_PREMORTEM" = "1" ] && JOBS="$JOBS premortem"
    git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork v2 Router" \
        commit -m "v2 router run $RUN_ID:$JOBS" 2>&1 | tail -2
    git push 2>&1 | tail -3
    cp recommendations.db "$WORKSPACE/recommendations.db"
  fi
  cd "$WORKSPACE"
else
  echo "All sub-jobs skipped (everything fresh); no push needed."
fi
```

## 4. FINAL REPORT

Output:
- Which sub-jobs ran vs skipped (with their freshness ages)
- Total signals saved (team + deterministic) and hold recs saved
- H1-H4 statuses if pre-mortem ran
- Push status
- Streamlit URL

## CONSTRAINTS

- This skill is designed to be IDEMPOTENT and FAST when nothing's due.
  A typical "everything fresh" run should complete in under 10 seconds.
- Each sub-job has its own skip-if-fresh check. The router does NOT
  override sub-job thresholds — it just orchestrates which ones to call.
- Don't push four separate commits — accumulate all DB changes and push
  once at §3.
- The Sunday-only gate for the hold monitor is optional (toggle in §1).
  Without it, the hold monitor will fire on the first router run after
  a 6-day gap, which is fine but not aligned to a weekend boundary.
