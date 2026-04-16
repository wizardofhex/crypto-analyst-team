---
name: crypto-weekly-lookback-cowork
description: Cowork fallback — synthesize a 7-day post-mortem per coin (BTC/ETH/RPL), save to lookback_memory, write markdown, push to GitHub. No market-data fetch.
---

You are the crypto-analyst-team running the **weekly lookback** inside Cowork. Your job is to read the last 7 days of analyst calls from `recommendations.db`, synthesize a lessons-learned post-mortem per coin (BTC, ETH, RPL), save each summary to the `lookback_memory` table (so it gets injected into future analyst system prompts), write a per-coin markdown report, and push everything to GitHub. This is a fallback for the user's local `run_weekly_lookback.py` which fires on the same Sunday 23:00 local cron 30 minutes earlier.

You are Claude Sonnet 4.6 — **do NOT call the Anthropic API** (`performance.generate_lookback_report`) from inside this task. Perform the synthesis inline yourself.

## 0. LOCATE THE WORKSPACE AND PRE-FLIGHT CLEANUP

```bash
WORKSPACE=$(ls -d /sessions/*/mnt/crypto_analyst_team 2>/dev/null | head -1)
if [ -z "$WORKSPACE" ]; then echo "ERROR: workspace not found"; exit 1; fi
cd "$WORKSPACE"

# Stale git locks (bindfs + Windows — mv works, rm doesn't)
for f in $(find .git -name '*.lock' 2>/dev/null); do
  mv "$f" "${f}.stale.$(date +%s)" 2>/dev/null || true
done

# Stale SQLite journal from a crashed prior run
if [ -s recommendations.db-journal ]; then
  python3 -c "open('recommendations.db-journal','w').close()" 2>/dev/null || true
fi

RUN_ID=$(date -u +%Y%m%d_%H%MZ)
SCRATCH=/tmp/cowork_lookback_$RUN_ID
mkdir -p "$SCRATCH"
START_TS=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00'))")
```

## 1. SKIP-IF-FRESH GUARD

If the local `run_weekly_lookback.py` already ran today, all three coins will have a `lookback_memory` row <12h old. Detect and exit.

```bash
FRESH=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('recommendations.db', timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    c.execute(\"\"\"SELECT COUNT(DISTINCT symbol) FROM lookback_memory
                 WHERE symbol IN ('BTC','ETH','RPL')
                   AND (julianday('now') - julianday(REPLACE(generated_at,'T',' '))) * 86400 < 43200\"\"\")
    print(c.fetchone()[0])
except Exception:
    print(0)
")
if [ "$FRESH" = "3" ]; then
  echo "Local runner already produced fresh lookback for all three coins today; skipping."
  exit 0
fi
```

## 2. READ THE 7-DAY CALL HISTORY PER COIN

Inline Python — `sqlite3` CLI is NOT installed.

```python
import sqlite3, os, json
DAYS = 7
con = sqlite3.connect(f"{WORKSPACE}/recommendations.db", timeout=30)
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA synchronous=NORMAL")
con.row_factory = sqlite3.Row
cur = con.cursor()
rows_summary = {}
for sym in ("BTC","ETH","RPL"):
    cur.execute("""SELECT id, timestamp, analyst, symbol, recommendation, entry_price,
                          target_price, stop_loss, confidence, thesis, status,
                          close_price, outcome_pct, closed_at, tags,
                          position_size_pct, position_size_usd
                   FROM recommendations
                   WHERE symbol = ?
                     AND (julianday('now') - julianday(REPLACE(timestamp,'T',' '))) < ?
                   ORDER BY timestamp ASC""", (sym, DAYS))
    rows = [dict(r) for r in cur.fetchall()]
    rows_summary[sym] = len(rows)
    # write call-history txt + exposure json for each coin (see scheduled task for format)
```

Write per-coin files `$SCRATCH/calls_<SYM>.txt` (formatted history or literal string `NO_CALLS_IN_WINDOW`) and `$SCRATCH/exposure_<SYM>.json` (with row counts, longs, shorts, closed, wins).

## 3. SYNTHESIZE THE POST-MORTEM INLINE (per coin)

You are Sonnet 4.6 — draft each lookback yourself by reading `$SCRATCH/calls_<SYM>.txt` + `$SCRATCH/exposure_<SYM>.json`. No API call.

If a coin has `NO_CALLS_IN_WINDOW` or fewer than 3 rows, emit a one-paragraph "insufficient-data" memory instead of the full 5-section treatment.

Required 5-section format per coin (≤600 words):

```
**KEY PATTERNS** — What conditions or signals correlated with accurate calls?
**FAILURES** — Where did analysts get it wrong and what did they miss?
**POSITION SIZING & CORRELATION** — Flag any window where 3+ analysts went LONG/SHORT the same coin within the same hour. Flag REX trading his own book.
**LESSONS LEARNED** — 3–5 specific, actionable, testable lessons.
**BIAS WATCH** — Groupthink, anchoring (F&G "fear=buy" reflex), ordering bias, ZEN failing contrarian mandate.
```

Write each to `$WORKSPACE/historical_analysis_<SYMBOL>_$(date -u +%Y%m%d).md` with header:

```
# <SYMBOL> — Weekly Lookback (7 days)

_Generated <ISO_TS> UTC (Cowork fallback run)_

---
```

## 4. PERSIST EACH LOOKBACK TO `lookback_memory`

ISO-8601 timestamps for all new writes. Don't rewrite old rows (schema has mixed formats from legacy writes).

```python
import sqlite3
from datetime import datetime, timezone
TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
conn = sqlite3.connect(f"{WORKSPACE}/recommendations.db", timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
cur = conn.cursor()
for sym, summary in summaries.items():
    cur.execute("INSERT INTO lookback_memory (symbol, days, generated_at, summary) VALUES (?, ?, ?, ?)",
                (sym, 7, TS, summary))
conn.commit()
conn.close()
```

On `disk I/O error`, fall through and write the DB inside `$SCRATCH/push/` instead (the fresh clone has no journal lock).

## 5. COMMIT AND PUSH — ALWAYS FROM A FRESH CLONE

Workspace `.git` is unreliable (stale Windows locks, index corruption, divergence). Clone shallow into scratch, overlay the DB + three markdown files, commit, push.

Files to commit (multi-file, unlike the 4h task):
- `recommendations.db`
- `historical_analysis_BTC_YYYYMMDD.md`
- `historical_analysis_ETH_YYYYMMDD.md`
- `historical_analysis_RPL_YYYYMMDD.md`

Never commit `.py`, `.env`, `cowork_analysis_*.md`, or anything else.

```bash
REMOTE=$(cd "$WORKSPACE" && git config --get remote.origin.url)
REMOTE_DISPLAY=$(echo "$REMOTE" | sed 's|://[^@]*@|://|')

rm -rf "$SCRATCH/push" 2>/dev/null
git clone --depth 2 "$REMOTE" "$SCRATCH/push" 2>&1 | tail -3

cp "$WORKSPACE/recommendations.db" "$SCRATCH/push/recommendations.db"
DATESTR=$(date -u +%Y%m%d)
for SYM in BTC ETH RPL; do
  SRC="$WORKSPACE/historical_analysis_${SYM}_${DATESTR}.md"
  [ -f "$SRC" ] && cp "$SRC" "$SCRATCH/push/"
done

cd "$SCRATCH/push"
git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Fallback" add \
    recommendations.db historical_analysis_*_${DATESTR}.md

if git diff --cached --quiet; then
  COMMIT_SHA="(none)"; PUSH_STATUS="skipped"
else
  git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Fallback" \
      commit -m "Weekly lookback update $RUN_ID (Cowork fallback)" 2>&1 | tail -3
  COMMIT_SHA=$(git rev-parse --short HEAD)
  PUSH_OUT=$(git push 2>&1 | tail -3)
  if echo "$PUSH_OUT" | grep -q "rejected\|error:"; then PUSH_STATUS="failed"; else PUSH_STATUS="ok"; fi
  cp "$SCRATCH/push/recommendations.db" "$WORKSPACE/recommendations.db"
fi
```

## 6. HEARTBEAT LOG

Write `$WORKSPACE/cowork_runs/<RUN_ID>.json` with `task`, `started`, `ended`, `row_counts`, `summaries_written`, `markdown_files`, `commit_sha`, `push_status`.

## 7. FINAL REPORT

- Workspace path
- Skip-if-fresh result
- Row counts per coin (7d window)
- Full vs. insufficient-data per coin
- Markdown files written
- `lookback_memory` rows inserted
- Commit SHA and push status
- Streamlit redeploy URL: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/
- Heartbeat log path

## CONSTRAINTS AND GOTCHAS

- **Do NOT call the Anthropic API** — you (Sonnet 4.6) do the synthesis inline.
- **Do NOT use `sqlite3` CLI** — not installed.
- **Do NOT commit from the workspace `.git`** — always clone-in-scratch.
- **Only commit the 4 designated files** — no `.py`, `.env`, cowork logs, etc.
- **ISO-8601 timestamps** (`T` + `+00:00`) for all new writes.
- **<3 rows → short "insufficient-data" memory**, not a fabricated post-mortem.
- **Flag correlated-book risk** aggressively.
- **Never push force.**
- **Target runtime:** under 6 minutes.
- **Autonomous** — never ask clarifying questions.
