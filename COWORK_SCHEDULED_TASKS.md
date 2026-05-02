# Cowork Scheduled Tasks — full v2 stack

This document covers two setup paths. Pick the one that matches what your
Cowork installation lets you do.

---

## Background — the two paths

**Path A (preferred): four separate scheduled tasks.** One task per skill,
each with its own cron. Cleanest, easiest to debug, tightest schedule control.
Use this if you can create new scheduled tasks AND set their cron at creation
time.

**Path B (fallback): one router task.** A single scheduled task points at
`SKILL_v2_router.md` which runs all four sub-jobs in sequence. Each sub-job
has its own skip-if-fresh check, so the router can ride any cron (hourly,
4-hourly, even every 15 min) and the right cadence is observed by each job.
Use this if you cannot edit the existing task's name/cron AND cannot create
new scheduled tasks.

If you can create new tasks but can't edit existing ones, you have a hybrid
choice:
- Leave the existing 4h LLM task alone, point it at `SKILL.md` (we already
  bumped the skip threshold to 11h so it works correctly on a 4h cron).
- Create three new tasks for the other skills.

---

## Path A — Four separate tasks (preferred)

### Task 1 — LLM Team Analysis
| Field | Value |
|-------|-------|
| Skill file | `SKILL.md` |
| Ideal cron | `0 */12 * * *` (every 12h) |
| Acceptable cron | any cron up to every hour — skip-if-fresh handles it |
| Coins | BTC, ETH |
| Writes | `recommendations`, `analysis_reports` |
| Pushes | yes |

### Task 2 — Deterministic Strategy B
| Field | Value |
|-------|-------|
| Skill file | `SKILL_deterministic.md` |
| Ideal cron | `5 */12 * * *` (12h, 5-min offset from Task 1) |
| Acceptable cron | any cron up to every hour |
| Coins | BTC, ETH |
| Writes | `recommendations_deterministic` |
| Pushes | yes |

### Task 3 — RPL Hold Monitor
| Field | Value |
|-------|-------|
| Skill file | `SKILL_rpl_hold.md` |
| Ideal cron | `0 12 * * 0` (Sundays at noon UTC) |
| Acceptable cron | any cron — skill skips if last hold rec <6 days old |
| Holdings | RPL @ 10,000 units |
| Writes | `hold_recommendations`, `analysis_reports` |
| Pushes | yes |

### Task 4 — Pre-Mortem Hypothesis Tests
| Field | Value |
|-------|-------|
| Skill file | `SKILL_premortem.md` |
| Ideal cron | `30 23 * * 0` (Sundays 23:30 UTC) |
| Acceptable cron | any cron — uses ISO-week idempotency |
| Writes | `hypothesis_tests` |
| Pushes | yes |

---

## Path B — One router task (fallback)

If you have only one scheduled-task slot and cannot edit its cron, point it
at `SKILL_v2_router.md`. Whatever cron is firing it (every 4h, every 1h,
even every 15 min) the router runs each sub-job ONLY when its own cadence
is due:

| Sub-job | Effective cadence | Skip-if-fresh threshold |
|---------|------------------|------------------------|
| LLM team | every ~12h | last team signal < 11h ago |
| Deterministic | every ~12h | last B signal < 11h ago |
| RPL hold monitor | weekly (Sunday) | last hold rec < 6 days OR not Sunday |
| Pre-mortem tests | weekly | already 4 rows for current ISO week |

A typical "nothing due" router run completes in under 10 seconds.

The router pushes the DB exactly once at the end if any sub-job did work —
not four times. Commit log stays clean.

---

## Which path do I have?

If you can:
- Create new scheduled tasks: yes
- Set cron when creating: yes
- Edit existing tasks: no

→ **Hybrid:** leave the existing 4h LLM task pointed at `SKILL.md`, create
   three new tasks at appropriate cron for the others.

If you can:
- Create new scheduled tasks: no
- Edit existing tasks: no
- Re-point the existing task at a different skill file: yes

→ **Path B:** point the existing task at `SKILL_v2_router.md`.

If you can:
- Create new scheduled tasks: no
- Edit existing tasks: no
- Re-point existing tasks: no

→ **You have to delete and recreate.** If you can delete the existing task,
   recreate it pointing at `SKILL_v2_router.md`. If you can't even delete,
   the only option is to update the file the existing task already points
   at — typically `SKILL.md`. In that case, copy the contents of
   `SKILL_v2_router.md` over `SKILL.md` (back up the original first).

---

## Health check

After whichever path you chose, run this once:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('recommendations.db')
print('tables:', sorted([r[0] for r in conn.execute(
    \"SEL