"""
run_deterministic_strategy.py — v2 plan (2026-05-02), Strategy B.

Pre-registered rule-based strategy that runs in parallel with the LLM team
on the same 12h cadence. Writes signals to recommendations_deterministic
(separate table, mirror schema) so HODL / Deterministic / LLM-Team curves
can be compared cleanly on the dashboard.

THE RULES BELOW ARE PRE-REGISTERED AND MUST NOT BE TUNED DURING THE TEST
WINDOW. That is the entire point of having a deterministic baseline:
if the rules can be tweaked retroactively, the comparison is meaningless.

Two entry patterns (matching what the lookbacks identified as the team's
real edge):

1. TREND_PULLBACK (LONG):
   price > EMA-200, RSI 40-55, ATR > 1.0x its 20-bar mean, funding <= 0.05%
   Mirror image for SHORT.

2. CAPITULATION (LONG):
   BB%B < 5, volume > 3x volume_sma_20, last candle bullish
   Mirror image (BLOW_OFF SHORT) for upper band.

Exits:
   stop = entry +/- 1.5x ATR
   target = entry +/- 3x ATR  (R:R = 1:2)
   time-stop = 48 hours (handled by tracker.expire_stale_positions)

Sizing: flat 1% of $124,000 = $1,240 per position.
        Max 2 concurrent same-direction positions per coin.

Cadence: same 12h cadence as the LLM team for fair comparison.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from data_fetcher import fetch_all_market_data
from indicators import calculate_all_indicators, calculate_atr
from config import DB_PATH, PORTFOLIO_SIZE
from tracker import init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("deterministic_strategy")


# ── Strategy parameters (PRE-REGISTERED — DO NOT TUNE) ────────────────────────

STRATEGY_VERSION = "deterministic-v1"
DEFAULT_COINS = ["BTC", "ETH"]
POSITION_SIZE_USD = 1240.0           # 1% of $124K
POSITION_SIZE_PCT = 1.0
MAX_CONCURRENT_PER_DIRECTION = 2
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 3.0
RSI_PULLBACK_LONG = (40, 55)
RSI_PULLBACK_SHORT = (45, 60)
ATR_RATIO_MIN = 1.0
FUNDING_CROWDED = 0.0005             # 0.05%
BB_PCT_B_CAPITULATION = 5
BB_PCT_B_BLOWOFF = 95
VOLUME_SPIKE_MULT = 3.0


# ── DB helpers (parallel table, same shape as `recommendations`) ──────────────

def init_deterministic_db() -> None:
    """Create the recommendations_deterministic table if missing."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations_deterministic (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT    NOT NULL,
                analyst           TEXT    NOT NULL,
                symbol            TEXT    NOT NULL,
                recommendation    TEXT    NOT NULL,
                entry_price       REAL,
                target_price      REAL,
                stop_loss         REAL,
                confidence        INTEGER,
                thesis            TEXT,
                status            TEXT    DEFAULT 'OPEN',
                close_price       REAL,
                outcome_pct       REAL,
                closed_at         TEXT,
                tags              TEXT,
                position_size_pct REAL,
                position_size_usd REAL
            )
            """
        )
        conn.commit()


def open_count(conn: sqlite3.Connection, symbol: str, direction: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM recommendations_deterministic "
        "WHERE status='OPEN' AND symbol=? AND recommendation=?",
        (symbol, direction),
    ).fetchone()[0]


def insert_signal(
    conn: sqlite3.Connection,
    symbol: str,
    direction: str,
    entry: float,
    target: float,
    stop: float,
    thesis: str,
    pattern_name: str,
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO recommendations_deterministic
          (timestamp, analyst, symbol, recommendation, entry_price, target_price,
           stop_loss, confidence, thesis, status, tags, position_size_pct, position_size_usd)
        VALUES (?, 'DETERMINISTIC', ?, ?, ?, ?, ?, 7, ?, 'OPEN', ?, ?, ?)
        """,
        (
            ts, symbol, direction, entry, target, stop, thesis,
            json.dumps([STRATEGY_VERSION, f"pattern:{pattern_name}", "guardrails-v2"]),
            POSITION_SIZE_PCT, POSITION_SIZE_USD,
        ),
    )
    conn.commit()
    return cur.lastrowid


def expire_and_close_deterministic(conn: sqlite3.Connection, symbol: str, current_price: float) -> Tuple[int, int]:
    """
    Apply target/stop/48h rules to OPEN deterministic positions.
    Returns (closed_target_stop_count, expired_time_count).
    """
    ts_now = datetime.now(timezone.utc).isoformat()
    closed_n = 0
    expired_n = 0

    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM recommendations_deterministic WHERE status='OPEN' AND symbol=?",
        (symbol,),
    ).fetchall()

    for r in rows:
        rid = r["id"]
        direction = r["recommendation"]
        entry = r["entry_price"]
        target = r["target_price"]
        stop = r["stop_loss"]

        if not entry or entry <= 0:
            continue

        # 48h time-stop check
        try:
            ts_str = r["timestamp"].replace("Z", "+00:00")
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)).total_seconds() / 3600.0
        except Exception:
            age_h = 0

        # target/stop hit?
        hit_target = hit_stop = False
        if direction == "LONG":
            if current_price >= target:
                hit_target = True
            elif current_price <= stop:
                hit_stop = True
        else:
            if current_price <= target:
                hit_target = True
            elif current_price >= stop:
                hit_stop = True

        new_status = None
        if hit_target or hit_stop:
            new_status = "CLOSED"
        elif age_h >= 48:
            new_status = "EXPIRED"

        if new_status is None:
            continue

        # P&L from direction
        if direction == "LONG":
            pnl_pct = round((current_price - entry) / entry * 100, 2)
        else:
            pnl_pct = round((entry - current_price) / entry * 100, 2)

        conn.execute(
            "UPDATE recommendations_deterministic SET status=?, close_price=?, outcome_pct=?, closed_at=? WHERE id=?",
            (new_status, current_price, pnl_pct, ts_now, rid),
        )
        if new_status == "CLOSED":
            closed_n += 1
        else:
            expired_n += 1

    conn.commit()
    return closed_n, expired_n


# ── Rule evaluators ───────────────────────────────────────────────────────────

def _atr_ratio(market_data: Dict[str, Any]) -> Optional[float]:
    """4h ATR / 20-bar mean ATR."""
    df = (market_data.get("ohlcv") or {}).get("4h")
    if df is None or df.empty or len(df) < 30:
        return None
    try:
        atr_series = calculate_atr(df["high"], df["low"], df["close"])
        cur_atr = float(atr_series.dropna().iloc[-1])
        mean_atr = float(atr_series.tail(20).mean())
        if mean_atr <= 0:
            return None
        return cur_atr / mean_atr
    except Exception:
        return None


def evaluate_rules(symbol: str, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Apply both entry patterns and return any signals that fire.
    Each signal dict has: direction, pattern, thesis, entry, target, stop.
    """
    signals: List[Dict[str, Any]] = []

    cg = market_data.get("coingecko") or {}
    price = cg.get("price")
    if price is None or price <= 0:
        return signals

    df_4h = (market_data.get("ohlcv") or {}).get("4h")
    if df_4h is None or df_4h.empty or len(df_4h) < 50:
        return signals

    ind = calculate_all_indicators(df_4h, timeframe="4h") or {}
    rsi = ind.get("rsi")
    ema_200 = ind.get("ema_200")
    atr = ind.get("atr")
    bb_pct_b = ind.get("bb_pct_b")
    last_bullish = ind.get("last_candle_bullish")
    vol_ratio = ind.get("volume_ratio")  # vol/sma in pct
    funding = market_data.get("funding_rate") or 0.0
    atr_ratio = _atr_ratio(market_data)

    if not all([rsi is not None, ema_200, atr, atr > 0]):
        return signals

    # ── Pattern 1: trend pullback ──
    if atr_ratio is not None and atr_ratio >= ATR_RATIO_MIN:
        if (
            price > ema_200
            and RSI_PULLBACK_LONG[0] <= rsi <= RSI_PULLBACK_LONG[1]
            and abs(funding) <= FUNDING_CROWDED
        ):
            signals.append({
                "direction": "LONG",
                "pattern": "trend_pullback_long",
                "thesis": (
                    f"price ${price:.2f} > EMA200 ${ema_200:.2f}, RSI={rsi}, "
                    f"ATR ratio={atr_ratio:.2f}x, funding={funding*100:.4f}% — "
                    f"trend-pullback long"
                ),
                "entry": price,
                "stop": price - ATR_STOP_MULT * atr,
                "target": price + ATR_TARGET_MULT * atr,
            })
        if (
            price < ema_200
            and RSI_PULLBACK_SHORT[0] <= rsi <= RSI_PULLBACK_SHORT[1]
            and abs(funding) <= FUNDING_CROWDED
        ):
            signals.append({
                "direction": "SHORT",
                "pattern": "trend_pullback_short",
                "thesis": (
                    f"price ${price:.2f} < EMA200 ${ema_200:.2f}, RSI={rsi}, "
                    f"ATR ratio={atr_ratio:.2f}x, funding={funding*100:.4f}% — "
                    f"trend-pullback short"
                ),
                "entry": price,
                "stop": price + ATR_STOP_MULT * atr,
                "target": price - ATR_TARGET_MULT * atr,
            })

    # ── Pattern 2: capitulation / blow-off ──
    if (
        bb_pct_b is not None
        and vol_ratio is not None
        and last_bullish is not None
    ):
        # Volume ratio is stored as percent (e.g. 350 = 3.5x). Threshold 300 = 3x.
        vol_mult = vol_ratio / 100.0
        if (
            bb_pct_b < BB_PCT_B_CAPITULATION
            and vol_mult > VOLUME_SPIKE_MULT
            and last_bullish
        ):
            signals.append({
                "direction": "LONG",
                "pattern": "capitulation_long",
                "thesis": (
                    f"BB%B={bb_pct_b:.1f} < 5, vol={vol_mult:.1f}x, bullish candle — "
                    f"capitulation long"
                ),
                "entry": price,
                "stop": price - ATR_STOP_MULT * atr,
                "target": price + ATR_TARGET_MULT * atr,
            })
        if (
            bb_pct_b > BB_PCT_B_BLOWOFF
            and vol_mult > VOLUME_SPIKE_MULT
            and not last_bullish
        ):
            signals.append({
                "direction": "SHORT",
                "pattern": "blow_off_short",
                "thesis": (
                    f"BB%B={bb_pct_b:.1f} > 95, vol={vol_mult:.1f}x, bearish candle — "
                    f"blow-off short"
                ),
                "entry": price,
                "stop": price + ATR_STOP_MULT * atr,
                "target": price - ATR_TARGET_MULT * atr,
            })

    return signals


# ── Per-coin orchestration ────────────────────────────────────────────────────

def run_for_coin(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper()
    logger.info("[%s] fetching market data", symbol)
    market_data = fetch_all_market_data(symbol)

    cg = market_data.get("coingecko") or {}
    current_price = cg.get("price")
    if current_price is None:
        logger.warning("[%s] no price — skipping", symbol)
        return {"symbol": symbol, "signals_saved": 0, "closed": 0, "expired": 0, "skipped": True}

    init_deterministic_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # First: close/expire any existing positions
        closed_n, expired_n = expire_and_close_deterministic(conn, symbol, current_price)

        # Then: evaluate rules
        signals = evaluate_rules(symbol, market_data)

        # Cap concurrent per-direction
        saved = 0
        for s in signals:
            current_open = open_count(conn, symbol, s["direction"])
            if current_open >= MAX_CONCURRENT_PER_DIRECTION:
                logger.info(
                    "[%s] %s rejected (already %d open)", symbol, s["direction"], current_open
                )
                continue

            rec_id = insert_signal(
                conn, symbol, s["direction"],
                s["entry"], s["target"], s["stop"],
                s["thesis"], s["pattern"],
            )
            saved += 1
            logger.info(
                "[%s] %s saved id=%d entry=%.2f target=%.2f stop=%.2f pattern=%s",
                symbol, s["direction"], rec_id,
                s["entry"], s["target"], s["stop"], s["pattern"],
            )

    return {
        "symbol": symbol,
        "price": current_price,
        "signals_saved": saved,
        "closed": closed_n,
        "expired": expired_n,
        "skipped": False,
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
        subprocess.run(
            ["git", "commit", "-m", f"Deterministic strategy update {ts}"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=repo_dir, check=True, capture_output=True)
        logger.info("Pushed DB to GitHub")
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Git push failed: %s", exc.stderr.decode() if exc.stderr else exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic baseline strategy runner (Strategy B)")
    parser.add_argument("coins", nargs="*", default=DEFAULT_COINS, help="Coins to evaluate")
    parser.add_argument("--push", action="store_true", help="Commit and push DB after run")
    args = parser.parse_args()

    init_db()
    init_deterministic_db()

    results = []
    for symbol in args.coins:
        try:
            results.append(run_for_coin(symbol))
        except Exception as exc:
            logger.error("[%s] failed: %s", symbol, exc)

    total_saved = sum(r.get("signals_saved", 0) for r in results)
    total_closed = sum(r.get("closed", 0) for r in results)
    total_expired = sum(r.get("expired", 0) for r in results)
    logger.info(
        "Deterministic run done: %d coins, %d saved, %d closed, %d expired",
        len(args.coins), total_saved, total_closed, total_expired,
    )

    if args.push and total_saved + total_closed + total_expired > 0:
        git_push_db()


if __name__ == "__main__":
    main()
