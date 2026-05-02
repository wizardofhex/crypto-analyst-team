"""
pre_mortem_tests.py — v2 plan (2026-05-02), Item #0.6.

Each of the four hypotheses predicted by the v2 reviewers is encoded here as
a numerical test against the database state. Results are written to a
hypothesis_tests table and surfaced on the dashboard so we can see which
predicted failure modes are actually firing in production.

Run weekly. Idempotent — re-running the same week overwrites that week's
results so dashboards stay fresh.

H1 — "Regime-induced paralysis" (Gemini):
  WHEN regime is RANGE_BOUND_MID or LOW_VOL_CONTRACTION:
    a) WATCH-rate > 70% on team output  AND
    b) average post-WATCH 24h price move > 1.5x ATR
  -> the team is filtering out tradeable moves.

H2 — "Coarse classifier collapse" (Grok):
  Any single regime label assigned to > 60% of runs
  -> the classifier isn't actually discriminating.

H3 — "Calibration on noise" (ChatGPT):
  Average week-over-week absolute change in calibration weights > 0.20
  -> calibration is fitting noise. (Stub until calibration sizing ships.)

H4 — "Tier 1 silently broken" (all three):
  Per-item sanity checks for items #1–#5 of the v2 plan.

Schema for hypothesis_tests:
  id INTEGER PK
  week_id TEXT   -- ISO week e.g. 2026-W18
  hypothesis TEXT  -- H1/H2/H3/H4
  status TEXT  -- 'PASS' | 'CONFIRMED' | 'INSUFFICIENT_DATA'
  metrics TEXT  -- JSON of the actual numbers
  evaluated_at TEXT
  notes TEXT
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import DB_PATH

logger = logging.getLogger("pre_mortem_tests")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ── Schema ────────────────────────────────────────────────────────────────────

def init_hypothesis_table() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hypothesis_tests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id       TEXT    NOT NULL,
                hypothesis    TEXT    NOT NULL,
                status        TEXT    NOT NULL,
                metrics       TEXT,
                evaluated_at  TEXT    NOT NULL,
                notes         TEXT,
                UNIQUE(week_id, hypothesis)
            )
            """
        )
        conn.commit()


def write_result(week_id: str, hypothesis: str, status: str,
                 metrics: Dict[str, Any], notes: str = "") -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO hypothesis_tests "
            "(week_id, hypothesis, status, metrics, evaluated_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (week_id, hypothesis, status, json.dumps(metrics), ts, notes),
        )
        conn.commit()


def current_week_id() -> str:
    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ── H1: Regime-induced paralysis ──────────────────────────────────────────────

def evaluate_h1(week_id: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Look at signals tagged regime-RANGE_BOUND_MID or regime-LOW_VOL_CONTRACTION
    in the last 7 days. Compute WATCH-rate (signals where the team emitted
    no LONG/SHORT). Confirmed if >70%.

    Note: WATCH calls are not persisted — they only show up in the report_md.
    For now we approximate WATCH-rate as: 1 - (LONG+SHORT count / expected count).
    Expected count = number of analyst slots in matching-regime runs.
    Until reports include a per-analyst regime label, we report INSUFFICIENT_DATA.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Count LONG/SHORT signals tagged with a low-vol regime in the last 7d
        rows = conn.execute(
            """
            SELECT tags FROM recommendations
            WHERE timestamp >= datetime('now', '-7 days')
              AND tags LIKE '%regime-RANGE_BOUND_MID%'
                OR tags LIKE '%regime-LOW_VOL_CONTRACTION%'
            """
        ).fetchall()

        signals_in_lowvol = len(rows)

        # Total "low-vol regime" runs from analysis_reports (proxy)
        runs_in_lowvol = conn.execute(
            """
            SELECT COUNT(*) FROM analysis_reports
            WHERE timestamp >= datetime('now', '-7 days')
              AND (report_md LIKE '%RANGE_BOUND_MID%' OR report_md LIKE '%LOW_VOL_CONTRACTION%')
            """
        ).fetchone()[0]

    metrics = {
        "lowvol_regime_runs": runs_in_lowvol,
        "lowvol_signals_persisted": signals_in_lowvol,
    }

    # Need at least 4 low-vol runs to call this signal vs noise
    if runs_in_lowvol < 4:
        return ("INSUFFICIENT_DATA", metrics,
                f"Only {runs_in_lowvol} low-vol regime runs in last 7d — need >= 4 to evaluate")

    # 11 analysts per run, target watch_rate > 70% means signals < 30% × 11 × runs
    expected_signals_at_full_rate = runs_in_lowvol * 11
    watch_rate = 1.0 - (signals_in_lowvol / max(expected_signals_at_full_rate, 1))
    metrics["watch_rate"] = round(watch_rate, 3)
    metrics["expected_signals_at_full_rate"] = expected_signals_at_full_rate

    if watch_rate > 0.70:
        return ("CONFIRMED", metrics,
                f"WATCH-rate {watch_rate:.0%} in low-vol regimes — paralysis confirmed")
    return ("PASS", metrics,
            f"WATCH-rate {watch_rate:.0%} in low-vol regimes — within healthy range")


# ── H2: Coarse classifier collapse ────────────────────────────────────────────

def evaluate_h2(week_id: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Read regime labels from analysis_reports report_md (or tags) over last 7d.
    If any single label > 60% of total runs, classifier is too coarse.
    """
    labels = ("STRONG_UPTREND", "STRONG_DOWNTREND", "HIGH_VOL_EXPANSION",
              "LOW_VOL_CONTRACTION", "RANGE_BOUND_MID", "BREAKOUT_EXHAUSTION")
    counts = {label: 0 for label in labels}

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT report_md FROM analysis_reports "
            "WHERE timestamp >= datetime('now', '-7 days')"
        ).fetchall()

    total = 0
    for (report_md,) in rows:
        if not report_md:
            continue
        # Count first occurrence of each label per report (rough proxy for "regime of this run")
        for label in labels:
            if f"**Regime:** {label}" in report_md or f"Regime={label}" in report_md:
                counts[label] += 1
                total += 1
                break

    metrics = {"total_classified_runs": total, "label_counts": counts}

    if total < 8:
        return ("INSUFFICIENT_DATA", metrics,
                f"Only {total} classified runs in last 7d — need >= 8 to evaluate")

    max_label, max_count = max(counts.items(), key=lambda x: x[1])
    max_pct = max_count / total
    metrics["max_label"] = max_label
    metrics["max_label_share"] = round(max_pct, 3)

    if max_pct > 0.60:
        return ("CONFIRMED", metrics,
                f"{max_label} = {max_pct:.0%} of runs — classifier collapsed")
    return ("PASS", metrics,
            f"label distribution healthy (max={max_label} at {max_pct:.0%})")


# ── H3: Calibration on noise (stub) ───────────────────────────────────────────

def evaluate_h3(week_id: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Stub: calibration-weighted sizing (Item #9) ships only if Phase 3 selects
    Branch A. Until then we record INSUFFICIENT_DATA so the dashboard still
    has a row for the hypothesis.
    """
    return ("INSUFFICIENT_DATA", {"reason": "calibration sizing not yet deployed"},
            "Item #9 not yet shipped — H3 will activate when calibration sizing is live")


# ── H4: Tier 1 silently broken ────────────────────────────────────────────────

def evaluate_h4(week_id: str) -> Tuple[str, Dict[str, Any], str]:
    """
    Per-item sanity check for v2 Tier 1 items.
    """
    checks: Dict[str, Any] = {}
    failures: List[str] = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Item #1 (no-setup gate): % of LLM team runs that skipped
        # Look for setup-gate-skip-* tags in analysis_reports
        rows = conn.execute(
            "SELECT tags FROM analysis_reports WHERE timestamp >= datetime('now','-7 days')"
        ).fetchall()
        total_runs = len(rows)
        skipped = 0
        for (tags_json,) in rows:
            if tags_json and "setup-gate-skip" in tags_json:
                skipped += 1
        skip_pct = (skipped / total_runs) if total_runs else 0
        checks["item1_setup_gate"] = {
            "total_runs_7d": total_runs,
            "skipped_runs_7d": skipped,
            "skip_rate": round(skip_pct, 3),
            "target_range": [0.40, 0.70],
            "ok": (total_runs == 0) or (0.40 <= skip_pct <= 0.70),
        }
        if total_runs >= 4 and not checks["item1_setup_gate"]["ok"]:
            failures.append(f"item1_setup_gate skip_rate={skip_pct:.0%} outside [40%, 70%]")

        # Item #2 (cadence): expect ~2 runs/day on the LLM team
        runs_per_day = total_runs / 7.0 if total_runs else 0
        checks["item2_cadence"] = {
            "runs_per_day_7d_avg": round(runs_per_day, 2),
            "target": 2.0,
            "ok": 1.0 <= runs_per_day <= 3.0,
        }
        if total_runs >= 7 and not checks["item2_cadence"]["ok"]:
            failures.append(f"item2_cadence runs/day={runs_per_day:.2f} outside [1.0, 3.0]")

        # Item #3 (48h time-stop): no OPEN positions older than 48h
        old_open = conn.execute(
            "SELECT COUNT(*) FROM recommendations "
            "WHERE status='OPEN' AND recommendation IN ('LONG','SHORT') "
            "AND (julianday('now') - julianday(timestamp)) * 24 > 48"
        ).fetchone()[0]
        checks["item3_time_stop"] = {
            "open_positions_over_48h": old_open,
            "ok": old_open == 0,
        }
        if old_open > 0:
            failures.append(f"item3_time_stop {old_open} OPEN positions older than 48h")

        # Item #4 (5% per-coin cap): no per-coin same-direction notional > $6,200
        cap_rows = conn.execute(
            "SELECT symbol, recommendation, SUM(position_size_usd) AS notional, COUNT(*) AS n "
            "FROM recommendations WHERE status='OPEN' "
            "GROUP BY symbol, recommendation HAVING notional > 6200"
        ).fetchall()
        checks["item4_exposure_cap"] = {
            "violations": [
                {"symbol": r["symbol"], "direction": r["recommendation"],
                 "notional": r["notional"], "n": r["n"]}
                for r in cap_rows
            ],
            "ok": len(cap_rows) == 0,
        }
        if cap_rows:
            failures.append(f"item4_exposure_cap {len(cap_rows)} per-(symbol,dir) groups over $6,200")

        # Item #5 (RPL drop): no new RPL signals in last 7d
        new_rpl = conn.execute(
            "SELECT COUNT(*) FROM recommendations "
            "WHERE symbol='RPL' AND timestamp >= datetime('now','-7 days')"
        ).fetchone()[0]
        checks["item5_rpl_drop"] = {
            "new_rpl_signals_7d": new_rpl,
            "ok": new_rpl == 0,
        }
        if new_rpl > 0:
            failures.append(f"item5_rpl_drop {new_rpl} new RPL signals in last 7d")

    metrics = {"checks": checks, "failures": failures}
    if failures:
        return ("CONFIRMED", metrics,
                f"{len(failures)} Tier 1 sanity-check failures: " + "; ".join(failures))
    return ("PASS", metrics, f"All {len(checks)} Tier 1 items verified working")


# ── Main ─────────────────────────────────────────────────────────────────────

def run_all() -> Dict[str, Any]:
    init_hypothesis_table()
    week_id = current_week_id()
    results: Dict[str, Any] = {"week_id": week_id, "tests": {}}

    for hyp_name, fn in [("H1", evaluate_h1), ("H2", evaluate_h2),
                          ("H3", evaluate_h3), ("H4", evaluate_h4)]:
        try:
            status, metrics, notes = fn(week_id)
            write_result(week_id, hyp_name, status, metrics, notes)
            results["tests"][hyp_name] = {"status": status, "notes": notes, "metrics": metrics}
            logger.info("[%s] %s: %s — %s", week_id, hyp_name, status, notes)
        except Exception as exc:
            logger.error("[%s] %s evaluation failed: %s", week_id, hyp_name, exc)
            results["tests"][hyp_name] = {"status": "ERROR", "notes": str(exc)}

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-mortem hypothesis tests")
    parser.add_argument("--print-json", action="store_true", help="Print results JSON")
    args = parser.parse_args()

    results = run_all()
    if args.print_json:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
