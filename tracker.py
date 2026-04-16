"""
tracker.py — SQLite-backed recommendation tracker.
Stores analyst calls, tracks outcomes, and persists lookback memory.
"""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DB_PATH

logger = logging.getLogger(__name__)

VALID_RECOMMENDATIONS = {"LONG", "SHORT", "WATCH", "AVOID", "NEUTRAL"}
VALID_STATUSES = {"OPEN", "CLOSED", "EXPIRED"}


def _connect(timeout: int = 30) -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL journal mode.

    WAL (Write-Ahead Logging) uses reusable -wal/-shm files instead of a
    -journal file that must be deleted after each commit.  This prevents the
    persistent "disk I/O error" caused by FUSE / bindfs / Google-Drive mounts
    where file deletion silently fails and leaves a stale rollback journal.
    """
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL, fewer fsyncs
    return conn


# ─── Schema ───────────────────────────────────────────────────────────────────


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT    NOT NULL,
                analyst           TEXT    NOT NULL,
                symbol            TEXT    NOT NULL,
                recommendation    TEXT    NOT NULL,   -- LONG/SHORT/WATCH/AVOID/NEUTRAL
                entry_price       REAL,
                target_price      REAL,
                stop_loss         REAL,
                confidence        INTEGER,            -- 1-10
                thesis            TEXT,
                status            TEXT    DEFAULT 'OPEN',  -- OPEN/CLOSED/EXPIRED
                close_price       REAL,
                outcome_pct       REAL,
                closed_at         TEXT,
                tags              TEXT,               -- JSON array
                position_size_pct REAL,               -- % of portfolio (e.g. 2.1)
                position_size_usd REAL                -- USD amount (e.g. 2604.0)
            );

            CREATE TABLE IF NOT EXISTS analyst_stats (
                analyst          TEXT PRIMARY KEY,
                total_calls      INTEGER DEFAULT 0,
                wins             INTEGER DEFAULT 0,
                losses           INTEGER DEFAULT 0,
                neutrals         INTEGER DEFAULT 0,
                total_return_pct REAL    DEFAULT 0.0,
                best_call_pct    REAL    DEFAULT 0.0,
                worst_call_pct   REAL    DEFAULT 0.0,
                updated_at       TEXT
            );

            CREATE TABLE IF NOT EXISTS lookback_memory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                days         INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                summary      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analysis_reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT    NOT NULL UNIQUE,   -- e.g. 20260416_0832Z
                timestamp    TEXT    NOT NULL,           -- ISO-8601
                coins        TEXT    NOT NULL,           -- JSON array e.g. ["BTC","ETH","RPL"]
                prices       TEXT,                       -- JSON dict e.g. {"BTC":74697,...}
                fear_greed   INTEGER,
                signals_count INTEGER DEFAULT 0,
                tags         TEXT,                       -- JSON array of data-quality flags
                report_md    TEXT    NOT NULL,            -- full markdown analyst output
                heartbeat    TEXT,                        -- JSON heartbeat log
                source       TEXT    DEFAULT 'cowork'     -- 'cowork' or 'local'
            );
            """
        )
        conn.commit()

        # ── Migrate existing databases: add position_size columns if missing ──
        for col, coltype in [
            ("position_size_pct", "REAL"),
            ("position_size_usd", "REAL"),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE recommendations ADD COLUMN {col} {coltype}"
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists — safe to ignore


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Recommendations ──────────────────────────────────────────────────────────


def save_recommendation(
    analyst: str,
    symbol: str,
    recommendation: str,
    entry_price: Optional[float],
    target_price: Optional[float],
    stop_loss: Optional[float],
    confidence: int,
    thesis: str,
    tags: Optional[List[str]] = None,
    position_size_pct: Optional[float] = None,
    position_size_usd: Optional[float] = None,
) -> int:
    """
    Persist a new recommendation and return its auto-generated ID.
    Raises ValueError for invalid recommendation types.
    """
    rec = recommendation.upper()
    if rec not in VALID_RECOMMENDATIONS:
        raise ValueError(f"Invalid recommendation '{rec}'. Must be one of {VALID_RECOMMENDATIONS}")

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO recommendations
              (timestamp, analyst, symbol, recommendation, entry_price,
               target_price, stop_loss, confidence, thesis, status, tags,
               position_size_pct, position_size_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            """,
            (
                _utcnow(),
                analyst,
                symbol.upper(),
                rec,
                entry_price,
                target_price,
                stop_loss,
                max(1, min(10, confidence)),
                thesis,
                json.dumps(tags or []),
                position_size_pct,
                position_size_usd,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def close_recommendation(
    rec_id: int,
    close_price: Optional[float] = None,
    status: str = "CLOSED",
) -> Optional[float]:
    """
    Mark a recommendation as closed and compute the outcome percentage.
    Returns the outcome % (positive = profit for direction of trade), or None if not found.

    Pass close_price=None for manual closes — outcome_pct will be left as None
    and the position will be marked with outcome='MANUAL' via a null close_price.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'.")

    with _connect() as conn:
        row = conn.execute(
            "SELECT recommendation, entry_price, analyst FROM recommendations WHERE id = ?",
            (rec_id,),
        ).fetchone()
        if not row:
            return None

        direction, entry_price, analyst_name = row

        if close_price is not None and entry_price and entry_price > 0:
            raw_pct = (close_price - entry_price) / entry_price * 100
            # Flip sign for SHORT — profit if price fell
            outcome_pct: Optional[float] = round(-raw_pct if direction == "SHORT" else raw_pct, 2)
        else:
            # Manual close — no price supplied, skip P&L calculation
            outcome_pct = None

        conn.execute(
            """
            UPDATE recommendations
            SET status = ?, close_price = ?, outcome_pct = ?, closed_at = ?
            WHERE id = ?
            """,
            (status, close_price, outcome_pct, _utcnow(), rec_id),
        )
        conn.commit()

    update_analyst_stats(analyst_name)
    return outcome_pct


def get_open_recommendations(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all OPEN recommendations, optionally filtered by symbol."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        if symbol:
            rows = conn.execute(
                "SELECT * FROM recommendations WHERE status = 'OPEN' AND symbol = ? ORDER BY timestamp DESC",
                (symbol.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM recommendations WHERE status = 'OPEN' ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_recent_calls(
    limit: int = 10,
    analyst_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return the most recent trade recommendations as a list of dicts.

    Fields returned:
        id, analyst, symbol, direction, entry_price, target_price, stop_price,
        confidence, status, outcome, entry_date, close_date, pnl_pct

    Args:
        limit:         Maximum number of rows to return.
        analyst_name:  If provided, filter to only this analyst's calls.
    """
    query = """
        SELECT
            id,
            analyst,
            symbol,
            recommendation  AS direction,
            entry_price,
            target_price,
            stop_loss       AS stop_price,
            confidence,
            status,
            thesis          AS outcome,
            timestamp       AS entry_date,
            closed_at       AS close_date,
            outcome_pct     AS pnl_pct
        FROM recommendations
    """
    params: List[Any] = []
    if analyst_name:
        query += " WHERE analyst = ?"
        params.append(analyst_name)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_recommendations_history(
    symbol: Optional[str] = None,
    days: int = 30,
    analyst: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recommendation history filtered by recency, symbol, and/or analyst."""
    conditions = ["timestamp >= datetime('now', ?)"]
    params: List[Any] = [f"-{days} days"]

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    if analyst:
        conditions.append("analyst = ?")
        params.append(analyst)

    query = f"SELECT * FROM recommendations WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC"
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(query, params).fetchall()]


# ─── Analyst Stats ────────────────────────────────────────────────────────────


def update_analyst_stats(analyst: str) -> None:
    """Recompute and upsert win/loss stats for one analyst from closed recs."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT outcome_pct FROM recommendations WHERE analyst = ? AND status = 'CLOSED' AND outcome_pct IS NOT NULL",
            (analyst,),
        ).fetchall()

        outcomes = [r[0] for r in rows]
        total = len(outcomes)
        wins = sum(1 for p in outcomes if p > 0)
        losses = sum(1 for p in outcomes if p < 0)
        neutrals = total - wins - losses
        total_return = sum(outcomes)
        best = max(outcomes) if outcomes else 0.0
        worst = min(outcomes) if outcomes else 0.0

        conn.execute(
            """
            INSERT OR REPLACE INTO analyst_stats
              (analyst, total_calls, wins, losses, neutrals, total_return_pct,
               best_call_pct, worst_call_pct, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (analyst, total, wins, losses, neutrals, total_return, best, worst, _utcnow()),
        )
        conn.commit()


def get_analyst_performance(analyst: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return performance rows for one or all analysts."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        if analyst:
            rows = conn.execute(
                "SELECT * FROM analyst_stats WHERE analyst = ?", (analyst,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM analyst_stats ORDER BY analyst"
            ).fetchall()
        return [dict(r) for r in rows]


# ─── Lookback Memory ──────────────────────────────────────────────────────────


def save_lookback_memory(symbol: str, days: int, summary: str) -> None:
    """Persist a lookback lesson summary for future prompt injection."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO lookback_memory (symbol, days, generated_at, summary) VALUES (?, ?, ?, ?)",
            (symbol.upper(), days, _utcnow(), summary),
        )
        conn.commit()


def get_latest_lookback_memory(symbol: str) -> Optional[str]:
    """Return the most recently generated lookback summary for a symbol."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT summary FROM lookback_memory WHERE symbol = ? ORDER BY generated_at DESC LIMIT 1",
            (symbol.upper(),),
        ).fetchone()
        return row[0] if row else None


# ─── Analysis Reports ────────────────────────────────────────────────────────


def save_analysis_report(
    run_id: str,
    timestamp: str,
    coins: List[str],
    report_md: str,
    prices: Optional[Dict[str, float]] = None,
    fear_greed: Optional[int] = None,
    signals_count: int = 0,
    tags: Optional[List[str]] = None,
    heartbeat: Optional[Dict[str, Any]] = None,
    source: str = "cowork",
) -> int:
    """Persist a full analysis report and return its auto-generated ID."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR REPLACE INTO analysis_reports
              (run_id, timestamp, coins, prices, fear_greed,
               signals_count, tags, report_md, heartbeat, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                timestamp,
                json.dumps(coins),
                json.dumps(prices) if prices else None,
                fear_greed,
                signals_count,
                json.dumps(tags or []),
                report_md,
                json.dumps(heartbeat) if heartbeat else None,
                source,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_analysis_reports(limit: int = 100) -> List[Dict[str, Any]]:
    """Return analysis reports, most recent first."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM analysis_reports ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_analysis_report(run_id: str) -> Optional[Dict[str, Any]]:
    """Return a single analysis report by run_id."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM analysis_reports WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None


# ─── Auto-close positions ─────────────────────────────────────────────────────


def check_and_close_positions(symbol: str, current_price: float) -> List[Dict[str, Any]]:
    """
    Check all OPEN LONG/SHORT positions for a symbol and auto-close any that
    have hit their target price or stop loss.

    Rules:
      LONG  → WIN if current_price >= target_price
              LOSS if current_price <= stop_loss
      SHORT → WIN if current_price <= target_price
              LOSS if current_price >= stop_loss

    Skips positions where entry_price, target_price, or stop_loss is None/0.

    Returns a list of dicts for every position that was closed this call:
      {id, analyst, symbol, direction, outcome, pnl_pct,
       entry_price, close_price, target_price, stop_loss,
       hit_target, hit_stop}
    """
    closed: List[Dict[str, Any]] = []
    try:
        open_recs = get_open_recommendations(symbol)
        for rec in open_recs:
            direction = rec.get("recommendation", "").upper()
            if direction not in ("LONG", "SHORT"):
                continue

            entry_price = rec.get("entry_price")
            target_price = rec.get("target_price")
            stop_loss = rec.get("stop_loss")

            # Skip positions that are missing required price levels
            if not entry_price or entry_price == 0:
                continue
            if target_price is None or stop_loss is None:
                continue

            hit_target = False
            hit_stop = False

            if direction == "LONG":
                if current_price >= target_price:
                    hit_target = True
                elif current_price <= stop_loss:
                    hit_stop = True
            else:  # SHORT
                if current_price <= target_price:
                    hit_target = True
                elif current_price >= stop_loss:
                    hit_stop = True

            if not hit_target and not hit_stop:
                continue

            # Compute P&L from the direction's perspective
            if direction == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
            pnl_pct = round(pnl_pct, 2)

            outcome = "WIN" if hit_target else "LOSS"

            # Persist the close — close_recommendation also updates analyst_stats
            try:
                close_recommendation(rec["id"], current_price)
            except Exception as exc:
                logger.warning(
                    "Failed to close position id=%s for %s: %s", rec["id"], symbol, exc
                )
                continue

            closed.append({
                "id": rec["id"],
                "analyst": rec["analyst"],
                "symbol": rec["symbol"],
                "direction": direction,
                "outcome": outcome,
                "pnl_pct": pnl_pct,
                "entry_price": entry_price,
                "close_price": current_price,
                "target_price": target_price,
                "stop_loss": stop_loss,
                "hit_target": hit_target,
                "hit_stop": hit_stop,
            })

    except Exception as exc:
        logger.warning("check_and_close_positions error for %s: %s", symbol, exc)

    return closed
