"""
run_scheduled_analysis.py — Headless analysis runner for scheduled/cron execution.

Runs all 11 analysts against a configurable list of coins, saves signals
to recommendations.db, and optionally commits + pushes the updated DB
to GitHub so the Streamlit Cloud dashboard stays fresh.

Usage:
    python run_scheduled_analysis.py                     # Analyze default coins
    python run_scheduled_analysis.py BTC ETH SOL AVAX    # Analyze specific coins
    python run_scheduled_analysis.py --push              # Analyze + git push
"""

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic

from agents import create_analyst_team
from config import ANALYST_ORDER
from data_fetcher import fetch_all_market_data
from tracker import (
    check_and_close_positions,
    get_latest_lookback_memory,
    init_db,
    save_analysis_report,
    save_recommendation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scheduled_analysis")

DEFAULT_COINS = ["BTC", "ETH", "SOL"]
MODEL = "claude-haiku-4-5-20251001"

# ─── Signal parser (mirrors main.py) ─────────────────────────────────────────

_SIGNAL_RE = re.compile(
    r"\[SIGNAL:\s*(?P<signal>LONG|SHORT|WATCH|AVOID|NEUTRAL)"
    r"(?:\s*\|\s*CONFIDENCE:\s*(?P<conf>\d+))?"
    r"(?:\s*\|\s*TARGET:\s*\$?(?P<target>[\d,.]+))?"
    r"(?:\s*\|\s*STOP:\s*\$?(?P<stop>[\d,.]+))?"
    r"(?:\s*\|\s*SIZE:\s*(?P<size_pct>[\d.]+)%\s*\(\$(?P<size_usd>[\d,.]+)\))?"
    r"(?:\s*\|\s*THESIS:\s*(?P<thesis>[^\]]+))?"
    r"\]",
    re.IGNORECASE,
)


def _parse_price(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_signal(
    response: str,
    analyst_name: str,
    symbol: str,
    current_price: Optional[float],
) -> Optional[int]:
    """Extract [SIGNAL: ...] from response and save LONG/SHORT to DB."""
    m = _SIGNAL_RE.search(response)
    if not m:
        return None

    signal = m.group("signal").upper()
    conf = int(m.group("conf") or 5)
    target = _parse_price(m.group("target"))
    stop = _parse_price(m.group("stop"))
    thesis = (m.group("thesis") or "").strip()

    size_pct: Optional[float] = None
    size_usd: Optional[float] = None
    if m.group("size_pct"):
        try:
            size_pct = float(m.group("size_pct"))
        except (ValueError, TypeError):
            pass
    if m.group("size_usd"):
        try:
            size_usd = float(m.group("size_usd").replace(",", ""))
        except (ValueError, TypeError):
            pass

    if signal not in ("LONG", "SHORT"):
        logger.info("%s: %s %s (not saved — %s)", analyst_name, signal, symbol, thesis[:60])
        return None

    try:
        rec_id = save_recommendation(
            analyst=analyst_name,
            symbol=symbol,
            recommendation=signal,
            entry_price=current_price,
            target_price=target,
            stop_loss=stop,
            confidence=conf,
            thesis=thesis,
            position_size_pct=size_pct,
            position_size_usd=size_usd,
        )
        logger.info(
            "%s: %s %s saved (id=%d) conf=%d target=%s stop=%s",
            analyst_name, signal, symbol, rec_id, conf, target, stop,
        )
        return rec_id
    except Exception as exc:
        logger.warning("Failed to save signal for %s: %s", analyst_name, exc)
        return None


# ─── Core analysis ────────────────────────────────────────────────────────────


def analyze_coin(
    symbol: str,
    team: Dict,
    client: anthropic.Anthropic,
) -> Dict[str, object]:
    """Run all analysts on a single coin.

    Returns a dict with keys:
      - signals_saved (int)
      - report_md (str): per-coin markdown section suitable for the report
      - price (Optional[float]): spot price used
      - fear_greed (Optional[int]): current F&G value (same across coins)
      - degraded (List[str]): data-quality tags picked up from market_data
    """
    symbol = symbol.upper()
    logger.info("Fetching market data for %s...", symbol)
    market_data = fetch_all_market_data(symbol)

    cg = market_data.get("coingecko", {})
    current_price: Optional[float] = cg.get("price")

    degraded: List[str] = []
    if cg.get("_rate_limited"):
        logger.warning("CoinGecko rate-limited for %s — proceeding with indicators only", symbol)
        degraded.append(f"cg-rate-limited-{symbol}")

    # Auto-close positions that hit target/stop
    closed_lines: List[str] = []
    if current_price:
        closed = check_and_close_positions(symbol, current_price)
        for c in closed:
            logger.info(
                "Auto-closed #%s %s %s at %s (%s)",
                c.get("id"), c.get("direction"), symbol,
                c.get("close_price"), c.get("outcome"),
            )
            closed_lines.append(
                f"- #{c.get('id')} {c.get('analyst')} {c.get('direction')} "
                f"@ ${c.get('entry_price')} → ${c.get('close_price')} "
                f"({c.get('outcome')}, {c.get('pnl_pct')}%)"
            )

    # Load lookback memory
    memory = get_latest_lookback_memory(symbol)

    # Fear & Greed is coin-independent but we surface it for the report
    fng_block = market_data.get("fear_greed", {}) or {}
    fear_greed_val: Optional[int] = fng_block.get("value")

    question = f"Give me your full analysis of {symbol} right now based on the live data above."
    prior_responses: List[Dict[str, str]] = []
    signals_saved = 0

    # Build per-coin report section
    lines: List[str] = []
    lines.append(f"## {symbol} — 11-Analyst Breakdown (spot ${current_price})")
    lines.append("")
    if closed_lines:
        lines.append("**Auto-closed positions this run:**")
        lines.extend(closed_lines)
        lines.append("")

    for name in ANALYST_ORDER:
        analyst = team[name]
        try:
            response = analyst.analyze(question, market_data, prior_responses, memory)
            prior_responses.append({"analyst": name, "role": analyst.role, "response": response})
            rec_id = parse_signal(response, name, symbol, current_price)
            if rec_id:
                signals_saved += 1
            lines.append(f"### {name} — {analyst.role}")
            lines.append("")
            lines.append(response.strip())
            lines.append("")
        except Exception as exc:
            logger.error("%s failed on %s: %s", name, symbol, exc)
            lines.append(f"### {name} — ERROR")
            lines.append("")
            lines.append(f"`{exc}`")
            lines.append("")
            degraded.append(f"{name}-failed-{symbol}")

    logger.info("%s analysis complete — %d signals saved", symbol, signals_saved)
    return {
        "signals_saved": signals_saved,
        "report_md": "\n".join(lines),
        "price": current_price,
        "fear_greed": fear_greed_val,
        "degraded": degraded,
    }


def git_push_db() -> bool:
    """Commit and push the updated recommendations.db to GitHub."""
    repo_dir = Path(__file__).parent
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        subprocess.run(
            ["git", "add", "recommendations.db"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir, capture_output=True,
        )
        if result.returncode == 0:
            logger.info("No DB changes to commit")
            return True

        subprocess.run(
            ["git", "commit", "-m", f"Scheduled analysis update {ts}"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        logger.info("Pushed updated recommendations.db to GitHub")
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Git push failed: %s", exc.stderr.decode() if exc.stderr else exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduled crypto analysis runner")
    parser.add_argument("coins", nargs="*", default=DEFAULT_COINS, help="Coins to analyze")
    parser.add_argument("--push", action="store_true", help="Commit and push DB after analysis")
    parser.add_argument("--model", default=MODEL, help=f"Claude model (default: {MODEL})")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    init_db()
    client = anthropic.Anthropic()
    team = create_analyst_team(client, args.model)

    start_dt = datetime.now(timezone.utc)
    run_id = start_dt.strftime("%Y%m%d_%H%MZ")
    run_ts = start_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    total_signals = 0
    section_mds: List[str] = []
    prices: Dict[str, float] = {}
    fear_greed: Optional[int] = None
    tags: List[str] = [f"local-runner", f"model:{args.model}"]

    for symbol in args.coins:
        try:
            result = analyze_coin(symbol, team, client)
            total_signals += int(result.get("signals_saved", 0))
            section_mds.append(str(result.get("report_md", "")))
            price = result.get("price")
            if isinstance(price, (int, float)):
                prices[symbol.upper()] = float(price)
            fg = result.get("fear_greed")
            if fear_greed is None and isinstance(fg, int):
                fear_greed = fg
            degraded = result.get("degraded") or []
            if isinstance(degraded, list):
                tags.extend(str(t) for t in degraded)
        except Exception as exc:
            logger.error("Failed to analyze %s: %s", symbol, exc)
            tags.append(f"analyze-failed-{symbol}")

    logger.info(
        "Scheduled run complete: %d coins, %d signals saved",
        len(args.coins), total_signals,
    )

    # ── Build + persist the full analysis report for the dashboard History page ──
    header = [
        f"# Scheduled Analysis — {run_ts}",
        "",
        f"**Run ID:** `{run_id}`  ",
        f"**Model:** `{args.model}`  ",
        f"**Coins:** {', '.join(args.coins)}  ",
        f"**Prices:** " + ", ".join(f"{k}=${v}" for k, v in prices.items()) + "  ",
        f"**Fear & Greed:** {fear_greed if fear_greed is not None else 'n/a'}  ",
        f"**Signals persisted (LONG/SHORT):** {total_signals}",
        "",
    ]
    full_md = "\n".join(header) + "\n\n" + "\n\n".join(section_mds)

    # Deduplicate tags while preserving order
    seen = set()
    dedup_tags = [t for t in tags if not (t in seen or seen.add(t))]

    try:
        report_id = save_analysis_report(
            run_id=run_id,
            timestamp=run_ts,
            coins=[c.upper() for c in args.coins],
            report_md=full_md,
            prices=prices or None,
            fear_greed=fear_greed,
            signals_count=total_signals,
            tags=dedup_tags,
            heartbeat={
                "run_id": run_id,
                "started": run_ts,
                "ended": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "coins": [c.upper() for c in args.coins],
                "prices": prices,
                "fear_greed": fear_greed,
                "signals_count": total_signals,
                "tags": dedup_tags,
                "model": args.model,
            },
            source="local",
        )
        logger.info("analysis_reports row saved id=%s run_id=%s", report_id, run_id)
    except Exception as exc:
        logger.error("Failed to save analysis_report: %s", exc)

    if args.push:
        git_push_db()


if __name__ == "__main__":
    main()
