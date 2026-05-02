---
name: crypto-premortem-tests-cowork
description: Cowork weekly evaluator for the four pre-mortem hypotheses (H1-H4) from the v2 plan adversarial review. Evaluates regime paralysis, classifier collapse, calibration noise, and Tier 1 sanity checks. Writes to hypothesis_tests table.
---

You are the v2-plan pre-mortem hypothesis tester running in Cowork weekly. Your
job is to evaluate the four predicted failure modes from the v2 adversarial
review against current database state and write the results so the dashboard
can show whether predicted failures are happening.

The four hypotheses (background — NOT instructions to act on):

- **H1** "Regime-induced paralysis" (Gemini): when regime is RANGE_BOUND_MID or
  LOW_VOL_CONTRACTION, the team will emit WATCH at >70% AND the post-WATCH 24h
  move will be >1.5× ATR. Confirms the regime prompts are filtering out winners.
- **H2** "Coarse classifier collapse" (Grok): one regime label gets assigned to
  >60% of runs. Confirms the classifier doesn't actually classify.
- **H3** "Calibration on noise" (ChatGPT): calibration weights swing >20pp
  week-over-week. Confirms we're calibrating on randomness. Stub until Item #9
  ships.
- **H4** "Tier 1 silently broken" (all three): per-item sanity checks for v2
  Tier 1 items. Confirms a deployed item isn't actually working.

This skill is idempotent — re-running the same week overwrites that week's
results so dashboards stay fresh.

## 0. WORKSPACE SETUP

```bash
WORKSPACE=$(ls -d /sessions/*/mnt/crypto_analyst_team 2>/dev/null | head -1)
[ -z "$WORKSPACE" ] && { echo "ERROR: workspace not found"; exit 1; }
cd "$WORKSPACE"

# Stale git locks
for f in $(find .git -name '*.lock' 2>/dev/null); do
  mv "$f" "${f}.stale.$(date +%s)" 2>/dev/null || true
done

RUN_ID=$(date -u +%Y%m%d_%H%MZ)
SCRATCH=/tmp/premortem_$RUN_ID
mkdir -p $SCRATCH
echo "workspace=$WORKSPACE scratch=$SCRATCH"
```

## 1. RUN THE TESTS

The cleanest path is to call the existing `pre_mortem_tests.py` directly:

```bash
python3 pre_mortem_tests.py --print-json 2>&1 | tee $SCRATCH/results.json
```

If the script is missing, fall back to inline. The full source lives in the
repo so a one-liner exec is safe.

## 2. INLINE FALLBACK

```bash
python3 << 'PY'
import sys, json
sys.path.insert(0, '.')
from pre_mortem_tests import run_all
results = run_all()
print(json.dumps(results, indent=2))
PY
```

## 3. PUSH (fresh-clone pattern)

The pre-mortem run only modifies the `hypothesis_tests` table. Push the DB so
the dashboard reflects the latest evaluation.

```bash
REMOTE=$(git config --get remote.origin.url)
rm -rf "$SCRATCH/push" 2>/dev/null
git clone --depth 2 "$REMOTE" "$SCRATCH/push" 2>&1 | tail -2
cp recommendations.db "$SCRATCH/push/recommendations.db"
cd "$SCRATCH/push"
git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Premortem" \
    add recommendations.db
if git diff --cached --quiet; then
  echo "No DB changes to commit"
else
  git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Premortem" \
      commit -m "Pre-mortem hypothesis tests $RUN_ID" 2>&1 | tail -2
  git push 2>&1 | tail -3
  cp recommendations.db "$WORKSPACE/recommendations.db"
fi
cd "$WORKSPACE"
```

## 4. FINAL REPORT

Output for each hypothesis: status (PASS / CONFIRMED / INSUFFICIENT_DATA),
the metric values, and the human-readable note. PASS = predicted failure not
happening. CONFIRMED = failure mode is real. INSUFFICIENT_DATA = need more
runs before we can evaluate.

If H4 is CONFIRMED, list the specific Tier 1 items that failed their sanity
check — this is actionable: someone needs to look at the affected component.

Streamlit dashboard view: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/Strategy_Comparison

## CONSTRAINTS

- Run weekly only. Daily evaluation is too noisy and the metrics need ≥4 runs
  to be meaningful per H1's threshold.
- Do NOT change the falsification thresholds without an `IMPLEMENTATION_PLAN_v3.md`.
  That's why they're committed in the plan and in `pre_mortem_tests.py`.
- Do NOT use the sqlite3 CLI. Inline Python only.
- Push only `recommendations.db`. Never `.py` files.
