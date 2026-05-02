"""
run_hold_monitor.py — v2 plan + hold portfolio (2026-05-02).

Weekly analyzer for long-term hold positions. Currently monitors RPL @ 10K units.

Different from run_scheduled_analysis.py in three ways:

1. DECISION SPACE: HOLD / ADD / TRIM / EXIT (not LONG / SHORT).
   No entry/stop/target — those are active-trading concepts. Hold decisions
   reason about position SIZE and STRUCTURAL risk, not swing entries.

2. ANALYST SUBSET: only the 7 personas whose domain is informative for
   long-term holds. Skipped: MARCUS (tape), VEGA (no options on RPL),
   DELTA (no perps), ZEN (contrarian fades aren't a hold framework).

3. CADENCE: weekly, not 12h. Long-term holds shouldn't churn on intraday tape.

Usage:
    python run_hold_monitor.py                          # all hold positions
    python run_hold_monitor.py RPL                      # specific symbol
    python run_hold_monitor.py RPL --push               # commit + push
    python run_hold_monitor.py --model claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic

from agents import Analyst
from data_fetcher import fetch_all_market_data
from regime_filter import classify_regime, regime_block
from tracker import (
    get_hold_position,
    get_hold_positions,
    init_db,
    save_analysis_report,
    save_hold_recommendation,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hold_monitor")

# Hold-mode analyst subset — only the 7 personas whose domain matters for a
# long-term hold decision. Skip MARCUS/VEGA/DELTA/ZEN.
HOLD_ANALYSTS = ["ARIA", "NOVA", "CHAIN", "QUANT", "DEFI", "ATLAS", "REX"]
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


# ── Signal parser for hold decisions ──────────────────────────────────────────

# Format the analysts emit in HOLD mode:
# [HOLD_SIGNAL: HOLD|ADD|TRIM|EXIT | URGENCY: LOW|MEDIUM|HIGH | UNITS: 1000 | PRICE: $1.85 | CONFIDENCE: 7 | THESIS: one-line summary]
_HOLD_RE = re.compile(
    r"\[HOLD_SIGNAL:\s*(?P<mode>HOLD|ADD|TRIM|EXIT)"
    r"(?:\s*\|\s*URGENCY:\s*(?P<urgency>LOW|MEDIUM|HIGH))?"
    r"(?:\s*\|\s*UNITS:\s*(?P<units>[\d,.]+))?"
    r"(?:\s*\|\s*PRICE:\s*\$?(?P<price>[\d,.]+))?"
    r"(?:\s*\|\s*CONFIDENCE:\s*(?P<conf>\d+))?"
    r"(?:\s*\|\s*THESIS:\s*(?P<thesis>[^\]]+))?"
    r"\]",
    re.IGNORECASE,
)


def _parse_num(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_hold_signal(
    response: str,
    run_id: str,
    analyst_name: str,
    symbol: str,
    current_price: Optional[float],
    position_units: Optional[float],
) -> Optional[int]:
    m = _HOLD_RE.search(response)
    if not m:
        return None
    mode = m.group("mode").upper()
    urgency = m.group("urgency").upper() if m.group("urgency") else None
    units = _parse_num(m.group("units"))
    price = _parse_num(m.group("price"))
    conf = int(m.group("conf") or 5)
    thesis = (m.group("thesis") or "").strip()

    try:
        rec_id = save_hold_recommendation(
            run_id=run_id,
            analyst=analyst_name,
            symbol=symbol,
            mode=mode,
            urgency=urgency,
            target_units=units,
            target_price=price,
            confidence=conf,
            thesis=thesis,
            current_price=current_price,
            position_units=position_units,
            tags=["hold-monitor-v1"],
        )
        logger.info(
            "[hold:%s] %s -> %s (urg=%s units=%s price=%s id=%d)",
            symbol, analyst_name, mode, urgency, units, price, rec_id,
        )
        return rec_id
    except Exception as exc:
        logger.warning("Failed to save hold rec for %s: %s", analyst_name, exc)
        return None


# ── Hold-mode prompt augmentation ─────────────────────────────────────────────

def hold_mode_block(symbol: str, units: float, current_price: Optional[float],
                     cost_basis: Optional[float], notes: Optional[str]) -> str:
    """The block injected ahead of every hold-mode prompt so analysts know they're advising on a held position."""
    cur_value = (units * current_price) if current_price else None
    lines = [
        "=== HOLD-MODE INSTRUCTIONS (v2 plan + hold portfolio) ===",
        f"You are NOT picking a swing trade. The user already OWNS {units:g} {symbol}.",
        f"Current position value: ${cur_value:,.0f}" if cur_value else "Current value: unknown",
        f"Cost basis: ${cost_basis:,.2f}" if cost_basis else "Cost basis: not specified — focus on go-forward decision, not P&L on entry.",
    ]
    if notes:
        lines.append(f"Notes: {notes}")
    lines += [
        "",
        "DECISION SPACE — pick exactly one:",
        "  HOLD  — maintain the position as-is. No action.",
        "  ADD   — buy more. Specify how many UNITS and at what PRICE level.",
        "  TRIM  — sell some. Specify how many UNITS and at what PRICE level.",
        "  EXIT  — sell all. Specify URGENCY: HIGH/MEDIUM/LOW.",
        "",
        "REASONING FOCUS (in your domain):",
        "  - Structural / fundamental risk that justifies a position change",
        "  - Long-horizon (weeks/months) outlook, not 4h tape",
        "  - Specific catalysts (unlocks, regulatory dates, ecosystem changes)",
        "",
        "OUTPUT FORMAT — end with EXACTLY ONE line:",
        "  [HOLD_SIGNAL: HOLD | URGENCY: LOW | CONFIDENCE: 7 | THESIS: one-line]",
        "  [HOLD_SIGNAL: ADD | URGENCY: MEDIUM | UNITS: 2000 | PRICE: $1.65 | CONFIDENCE: 6 | THESIS: scale in on dip]",
        "  [HOLD_SIGNAL: TRIM | URGENCY: MEDIUM | UNITS: 3000 | PRICE: $2.40 | CONFIDENCE: 7 | THESIS: scale out on rally]",
        "  [HOLD_SIGNAL: EXIT | URGENCY: HIGH | CONFIDENCE: 8 | THESIS: structural break]",
        "",
        "DEFAULT TO HOLD if you cannot make a confident structural case for change.",
        "Frequent churning on a long-term position destroys edge. Be patient.",
        "=" * 60,
    ]
    return "\n".join(lines)


# ── Per-symbol orchestration ──────────────────────────────────────────────────

def analyze_hold(
    symbol: str,
    position_units: float,
    cost_basis: Optional[float],
    notes: Optional[str],
    client: anthropic.Anthropic,
    model: str,
    run_id: str,
) -> Dict[str, Any]:
    symbol = symbol.upper()
    logger.info("[hold:%s] fetching market data for %d units", symbol, int(position_units))

    market_data = fetch_all_market_data(symbol)
    cg = market_data.get("coingecko") or {}
    current_price: Optional[float] = cg.get("price")

    # Build context blocks
    hold_block = hold_mode_block(symbol, position_units, current_price, cost_basis, notes)
    regime = classify_regime(symbol, market_data)
    regime_md = regime_block(regime)
    combined_context = hold_block + "\n\n" + regime_md

    question = (
        f"Should we HOLD / ADD / TRIM / EXIT our {position_units:g} {symbol} long-term "
        f"position based on the live data above? Current spot ${current_price}. "
        "Reason in your domain only — don't try to do other analysts' jobs."
    )

    prior_responses: List[Dict[str, str]] = []
    saved = 0
    section_md: List[str] = []
    section_md.append(f"## {symbol} -- Hold Monitor (position: {position_units:g} units, ~${(position_units * (current_price or 0)):,.0f})")
    section_md.append("")
    section_md.append(f"**Regime:** {regime.get('label')} -- {regime.get('reasoning')}")
    section_md.append("")

    for name in HOLD_ANALYSTS:
        try:
            analyst = Analyst(name, client, model=model)
            response = analyst.analyze(question, market_data, prior_responses, combined_context)
            prior_responses.append({"analyst": name, "role": analyst.role, "response": response})

            rec_id = parse_hold_signal(
                response, run_id, name, symbol, current_price, position_units,
            )
            if rec_id:
                saved += 1

            section_md.append(f"### {name} -- {analyst.role}")
            section_md.append("")
            section_md.append(response.strip())
            section_md.append("")
        except Exception as exc:
            logger.error("[hold:%s] %s failed: %s", symbol, name, exc)
            section_md.append(f"### {name} -- ERROR\n\n`{exc}`\n")

    return {
        "symbol": symbol,
        "current_price": current_price,
        "position_units": position_units,
        "saved": saved,
        "report_md": "\n".join(section_md),
    }


def git_push_db() -> bool:
    repo_dir = Path(__file__).parent
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        subprocess.run(["git", "add", "recommendations.db"], cwd=repo_dir, check=True, capture_output=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, capture_output=True)
        if result.returncode == 0:
            logger.info("No DB changes to commit")
            return True
        subprocess.run(["git", "commit", "-m", f"Hold monitor update {ts}"],
                       cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True, capture_output=True)
        logger.info("Pushed hold update to GitHub")
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Git push failed: %s", exc.stderr.decode() if exc.stderr else exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-term hold monitor (weekly cadence)")
    parser.add_argument("symbols", nargs="*", help="Specific hold symbols (default: all)")
    parser.add_argument("--push", action="store_true", help="Commit + push DB after run")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    init_db()

    if args.symbols:
        positions = []
        for s in args.symbols:
            p = get_hold_position(s)
            if p:
                positions.append(p)
            else:
                logger.warning("No hold position recorded for %s -- skipping", s)
    else:
        positions = get_hold_positions()

    if not positions:
        logger.warning("No hold positions to monitor. Add via tracker.upsert_hold_position(...)")
        return

    client = anthropic.Anthropic()
    start_dt = datetime.now(timezone.utc)
    run_id = "hold_" + start_dt.strftime("%Y%m%d_%H%MZ")
    run_ts = start_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    section_mds: List[str] = []
    total_saved = 0
    prices: Dict[str, float] = {}
    tags = ["hold-monitor-v1", f"model:{args.model}"]

    for p in positions:
        try:
            result = analyze_hold(
                symbol=p["symbol"],
                position_units=p["units"],
                cost_basis=p.get("cost_basis"),
                notes=p.get("notes"),
                client=client,
                model=args.model,
                run_id=run_id,
            )
            total_saved += result["saved"]
            section_mds.append(result["report_md"])
            if result.get("current_price"):
                prices[p["symbol"]] = result["current_price"]
        except Exception as exc:
            logger.error("Hold analysis failed for %s: %s", p["symbol"], exc)
            tags.append(f"hold-failed-{p['symbol']}")

    header = [
        f"# Hold Monitor -- {run_ts}",
        "",
        f"**Run ID:** `{run_id}`  ",
        f"**Model:** `{args.model}`  ",
        f"**Symbols:** {', '.join(p['symbol'] for p in positions)}  ",
        f"**Hold recommendations saved:** {total_saved}",
        "",
    ]
    full_md = "\n".join(header) + "\n\n" + "\n\n".join(section_mds)

    try:
        save_analysis_report(
            run_id=run_id,
            timestamp=run_ts,
            coins=[p["symbol"] for p in positions],
            report_md=full_md,
            prices=prices or None,
            signals_count=total_saved,
            tags=tags,
            heartbeat={
                "run_id": run_id, "started": run_ts,
                "ended": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "symbols": [p["symbol"] for p in positions],
                "prices": prices, "saved": total_saved, "tags": tags, "model": args.model,
            },
            source="local-hold",
        )
    except Exception as exc:
        logger.error("Failed to save analysis_report: %s", exc)

    logger.info("Hold monitor done: %d symbols, %d recommendations saved", len(positions), total_saved)

    if args.push:
        git_push_db()


if __name__ == "__main__":
    main()
