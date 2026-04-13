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
) -> int:
    """Run all analysts on a single coin. Returns number of signals saved."""
    symbol = symbol.upper()
    logger.info("Fetching market data for %s...", symbol)
    market_data = fetch_all_market_data(symbol)

    cg = market_data.get("coingecko", {})
    current_price: Optional[float] = cg.get("price")

    if cg.get("_rate_limited"):
        logger.warning("CoinGecko rate-limited for %s — proceeding with indicators only", symbol)

    # Auto-close positions that hit target/stop
    if current_price:
        closed = check_and_close_positions(symbol, current_price)
        for c in closed:
            logger.info(
                "Auto-closed #%s %s %s at %s (%s)",
                c.get("id"), c.get("direction"), symbol,
                c.get("close_price"), c.get("outcome"),
            )

    # Load lookback memory
    memory = get_latest_lookback_memory(symbol)

    question = f"Give me your full analysis of {symbol} right now based on the live data above."
    prior_responses: List[Dict[str, str]] = []
    signals_saved = 0

    for name in ANALYST_ORDER:
        analyst = team[name]
        try:
            response = analyst.analyze(question, market_data, prior_responses, memory)
            prior_responses.append({"analyst": name, "role": analyst.role, "response": response})
            rec_id = parse_signal(response, name, symbol, current_price)
            if rec_id:
                signals_saved += 1
        except Exception as exc:
            logger.error("%s failed on %s: %s", name, symbol, exc)

    logger.info("%s analysis complete — %d signals saved", symbol, signals_saved)
    return signals_saved


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

    total_signals = 0
    for symbol in args.coins:
        try:
            total_signals += analyze_coin(symbol, team, client)
        except Exception as exc:
            logger.error("Failed to analyze %s: %s", symbol, exc)

    logger.info(
        "Scheduled run complete: %d coins, %d signals saved",
        len(args.coins), total_signals,
    )

    if args.push:
        git_push_db()


if __name__ == "__main__":
    main()
