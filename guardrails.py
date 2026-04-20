"""
guardrails.py — Pre-prompt guardrails that inject risk-aware context into each
analyst's system prompt before they decide a direction.

These guardrails are the enforcement layer that the weekly lookback has been
repeatedly asking for:
  1. Exposure guard      — blocks same-direction pileups that make 11 votes
                           behave like 1 vote.
  2. Cooldown guard      — stops re-entry into the same losing thesis within
                           12 hours of a closed loss.
  3. Confidence calibration — surfaces an analyst's rolling conf-vs-outcome
                              history so confidence scores become honest.

All helpers are read-only against recommendations.db and safe to call from
inside the analyst loop. They degrade gracefully — if the DB read fails, the
caller gets an empty block and the analyst proceeds without the extra context.

Introduced: 2026-04-20 per weekly-lookback recommendations.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import DB_PATH, PORTFOLIO_SIZE

logger = logging.getLogger(__name__)

# ─── Tunables ─────────────────────────────────────────────────────────────────

# An exposure guard fires when same-direction open notional on a coin exceeds
# this fraction of the $124K portfolio. Historical data (4/13–4/19) shows the
# team piled up to ~18% of the book on one hour; 10% is a hard warning line.
EXPOSURE_WARN_PCT = 10.0

# A "hard cap" above which incremental same-direction calls must downgrade to
# WATCH or size ≤0.5%. Picked generously — this still allows meaningful size.
EXPOSURE_CAP_PCT = 15.0

# Cooldown window after a closed losing position in a given (symbol, direction).
COOLDOWN_HOURS = 12

# Calibration lookback window (days).
CALIBRATION_DAYS = 30

# Minimum sample size before we surface a calibration number. Below this we
# would be showing statistical noise.
CALIBRATION_MIN_N = 4


# ─── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ExposureSnapshot:
    symbol: str
    long_count: int = 0
    short_count: int = 0
    long_usd: float = 0.0
    short_usd: float = 0.0
    long_analysts: List[str] = field(default_factory=list)
    short_analysts: List[str] = field(default_factory=list)

    @property
    def long_pct_of_portfolio(self) -> float:
        if not PORTFOLIO_SIZE:
            return 0.0
        return self.long_usd / PORTFOLIO_SIZE * 100

    @property
    def short_pct_of_portfolio(self) -> float:
        if not PORTFOLIO_SIZE:
            return 0.0
        return self.short_usd / PORTFOLIO_SIZE * 100


@dataclass
class CooldownHit:
    analyst: str
    direction: str
    outcome_pct: float
    hours_ago: float
    entry_price: Optional[float]
    thesis: str


# ─── DB helpers (read-only) ───────────────────────────────────────────────────


def _connect_ro() -> sqlite3.Connection:
    """Read-only connection — guardrails never write to the DB."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def compute_exposure(symbol: str) -> ExposureSnapshot:
    """Return open LONG/SHORT exposure on one coin."""
    snap = ExposureSnapshot(symbol=symbol.upper())
    try:
        with _connect_ro() as conn:
            rows = conn.execute(
                """
                SELECT analyst, recommendation, position_size_usd
                FROM recommendations
                WHERE status = 'OPEN' AND symbol = ?
                """,
                (symbol.upper(),),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("compute_exposure read failed for %s: %s", symbol, exc)
        return snap

    for r in rows:
        direction = (r["recommendation"] or "").upper()
        usd = r["position_size_usd"] or 0.0
        analyst = r["analyst"] or "?"
        if direction == "LONG":
            snap.long_count += 1
            snap.long_usd += float(usd)
            snap.long_analysts.append(analyst)
        elif direction == "SHORT":
            snap.short_count += 1
            snap.short_usd += float(usd)
            snap.short_analysts.append(analyst)
    return snap


def find_recent_closed_losses(
    symbol: str,
    hours: int = COOLDOWN_HOURS,
) -> List[CooldownHit]:
    """
    Return closed losing positions on this symbol within the last `hours`.
    Used by the cooldown guard to discourage immediate re-entry.
    """
    hits: List[CooldownHit] = []
    try:
        with _connect_ro() as conn:
            rows = conn.execute(
                """
                SELECT analyst, recommendation, entry_price, outcome_pct,
                       thesis, closed_at,
                       (julianday('now') - julianday(REPLACE(closed_at,'T',' '))) * 24
                           AS hours_ago
                FROM recommendations
                WHERE status = 'CLOSED'
                  AND symbol = ?
                  AND outcome_pct IS NOT NULL
                  AND outcome_pct < 0
                  AND closed_at IS NOT NULL
                  AND (julianday('now') - julianday(REPLACE(closed_at,'T',' '))) * 24 <= ?
                ORDER BY closed_at DESC
                """,
                (symbol.upper(), hours),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("find_recent_closed_losses read failed for %s: %s", symbol, exc)
        return hits

    for r in rows:
        hits.append(
            CooldownHit(
                analyst=r["analyst"] or "?",
                direction=(r["recommendation"] or "").upper(),
                outcome_pct=float(r["outcome_pct"]),
                hours_ago=float(r["hours_ago"] or 0.0),
                entry_price=r["entry_price"],
                thesis=(r["thesis"] or "")[:200],
            )
        )
    return hits


def get_confidence_calibration(
    analyst: str,
    symbol: str,
    days: int = CALIBRATION_DAYS,
) -> Dict[int, Dict[str, float]]:
    """
    Return rolling conf→outcome stats for one analyst on one coin over `days`.

    Shape:
      {5: {"n": 8, "wins": 3, "win_rate": 0.375, "avg_pct": -0.1}, ...}

    Only closed positions with a numeric outcome_pct are counted. Empty dict
    on read failure or if there's no history.
    """
    out: Dict[int, Dict[str, float]] = {}
    try:
        with _connect_ro() as conn:
            rows = conn.execute(
                """
                SELECT confidence, outcome_pct
                FROM recommendations
                WHERE analyst = ? AND symbol = ?
                  AND status = 'CLOSED'
                  AND outcome_pct IS NOT NULL
                  AND confidence IS NOT NULL
                  AND timestamp >= datetime('now', ?)
                """,
                (analyst, symbol.upper(), f"-{days} days"),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("get_confidence_calibration read failed: %s", exc)
        return out

    buckets: Dict[int, List[float]] = {}
    for r in rows:
        conf = int(r["confidence"])
        buckets.setdefault(conf, []).append(float(r["outcome_pct"]))

    for conf, pcts in buckets.items():
        n = len(pcts)
        if n < CALIBRATION_MIN_N:
            continue
        wins = sum(1 for p in pcts if p > 0)
        out[conf] = {
            "n": n,
            "wins": wins,
            "win_rate": round(wins / n, 3),
            "avg_pct": round(sum(pcts) / n, 2),
        }
    return out


# ─── Block builders (what gets injected into the prompt) ─────────────────────


def _render_exposure_block(snap: ExposureSnapshot) -> Optional[str]:
    """Render the exposure snapshot as a plain-text warning block, or None if
    nothing notable to say."""
    long_pct = snap.long_pct_of_portfolio
    short_pct = snap.short_pct_of_portfolio
    if long_pct < EXPOSURE_WARN_PCT and short_pct < EXPOSURE_WARN_PCT:
        return None

    lines = ["=== OPEN BOOK EXPOSURE — PRE-CALL CHECK ==="]

    if long_pct >= EXPOSURE_WARN_PCT:
        severity = "HARD CAP" if long_pct >= EXPOSURE_CAP_PCT else "WARNING"
        lines.append(
            f"  {severity}: {snap.symbol} LONG book already at "
            f"{long_pct:.1f}% of ${PORTFOLIO_SIZE:,} "
            f"({snap.long_count} open calls by {', '.join(sorted(set(snap.long_analysts)))})."
        )
        if long_pct >= EXPOSURE_CAP_PCT:
            lines.append(
                f"  If your call is LONG {snap.symbol}, you MUST either "
                f"downgrade to WATCH or size ≤0.5% (${PORTFOLIO_SIZE * 0.005:,.0f}). "
                "A fresh 2% long at this exposure level is a correlated-book bet, "
                "not an independent call."
            )
        else:
            lines.append(
                f"  If your call is LONG {snap.symbol}, consider downgrading "
                "size by 50% or requiring a fresh, non-overlapping thesis."
            )

    if short_pct >= EXPOSURE_WARN_PCT:
        severity = "HARD CAP" if short_pct >= EXPOSURE_CAP_PCT else "WARNING"
        lines.append(
            f"  {severity}: {snap.symbol} SHORT book already at "
            f"{short_pct:.1f}% of ${PORTFOLIO_SIZE:,} "
            f"({snap.short_count} open calls by {', '.join(sorted(set(snap.short_analysts)))})."
        )
        if short_pct >= EXPOSURE_CAP_PCT:
            lines.append(
                f"  If your call is SHORT {snap.symbol}, you MUST either "
                f"downgrade to WATCH or size ≤0.5%."
            )

    # Conflict note
    if snap.long_count and snap.short_count:
        lines.append(
            f"  CONFLICT: {snap.long_count}L vs {snap.short_count}S open on "
            f"{snap.symbol}. The team is already hedging itself into noise."
        )

    lines.append("=" * 44)
    return "\n".join(lines)


def _render_cooldown_block(symbol: str, hits: List[CooldownHit]) -> Optional[str]:
    """Render a cooldown warning block if we have recent closed losses."""
    if not hits:
        return None

    lines = [f"=== RECENT CLOSED LOSSES ON {symbol.upper()} (last {COOLDOWN_HOURS}h) ==="]
    for h in hits[:4]:  # cap at 4 — prompt bloat otherwise
        lines.append(
            f"  {h.analyst} {h.direction} closed {h.outcome_pct:+.1f}% "
            f"{h.hours_ago:.1f}h ago. Thesis: {h.thesis[:140]}"
        )
    lines.append(
        f"  If your call matches one of these directions, either (a) cite a "
        f"NEW signal not present in the prior losing thesis, or (b) downgrade "
        f"to WATCH. Reflex re-entry into the same losing read is the single "
        f"biggest P&L leak in the 7d lookback."
    )
    lines.append("=" * 44)
    return "\n".join(lines)


def _render_calibration_block(
    analyst: str,
    symbol: str,
    calib: Dict[int, Dict[str, float]],
) -> Optional[str]:
    """Render an analyst's confidence calibration as a plain-text block."""
    if not calib:
        return None

    # Summary line per confidence bucket, sorted ascending by conf
    rows = []
    for conf in sorted(calib.keys()):
        c = calib[conf]
        rows.append(
            f"  conf={conf}: win_rate={c['win_rate']:.0%}  "
            f"avg_outcome={c['avg_pct']:+.2f}%  n={int(c['n'])}"
        )

    header = (
        f"=== YOUR {CALIBRATION_DAYS}-DAY CONFIDENCE CALIBRATION "
        f"— {analyst} on {symbol.upper()} ==="
    )
    footer = (
        "  Use this to calibrate your score. If your conf=7 calls have a "
        "sub-25% win rate, a conf=7 today is likely overconfidence — downgrade "
        "to conf=5 unless you can cite a signal absent from your prior losing calls."
    )
    return "\n".join([header, *rows, footer, "=" * 44])


def build_guardrail_block(
    analyst: str,
    symbol: str,
    include_exposure: bool = True,
    include_cooldown: bool = True,
    include_calibration: bool = True,
) -> str:
    """
    Build the full guardrail block for one (analyst, symbol). Callers inject
    this into each analyst's system prompt before the memory section.

    Returns an empty string when there is nothing notable — that way the
    prompt stays short in the common case where the book is small and there
    are no recent closed losses.
    """
    blocks: List[str] = []

    if include_exposure:
        snap = compute_exposure(symbol)
        b = _render_exposure_block(snap)
        if b:
            blocks.append(b)

    if include_cooldown:
        hits = find_recent_closed_losses(symbol, hours=COOLDOWN_HOURS)
        b = _render_cooldown_block(symbol, hits)
        if b:
            blocks.append(b)

    if include_calibration:
        calib = get_confidence_calibration(analyst, symbol, days=CALIBRATION_DAYS)
        b = _render_calibration_block(analyst, symbol, calib)
        if b:
            blocks.append(b)

    return "\n\n".join(blocks)


# ─── REX post-call parser ─────────────────────────────────────────────────────

import re

_EXPOSURE_BLOCK_RE = re.compile(
    r"EXPOSURE_BLOCK\s*:\s*(?P<value>YES|NO)",
    re.IGNORECASE,
)


def parse_rex_exposure_block(response: str) -> Optional[bool]:
    """
    REX is required to emit `EXPOSURE_BLOCK: yes` or `EXPOSURE_BLOCK: no` on
    each call. This parses that directive out of REX's response so the runner
    can pass a downstream note into ZEN.

    Returns:
        True  — REX declared an exposure block (downstream should downgrade)
        False — REX explicitly cleared exposure
        None  — REX did not emit the directive (legacy response)
    """
    m = _EXPOSURE_BLOCK_RE.search(response or "")
    if not m:
        return None
    return m.group("value").upper() == "YES"


def render_rex_block_note(rex_blocked: bool) -> str:
    """Short note to append to ZEN (or any subsequent analyst) after REX."""
    if rex_blocked:
        return (
            "=== REX EXPOSURE_BLOCK DIRECTIVE ===\n"
            "  REX has declared the book over-exposed on this call. If your "
            "call is directional (LONG or SHORT), you MUST either downgrade to "
            "WATCH or size ≤0.5%. REX's block supersedes your thesis-level "
            "conviction until exposure falls below the warning line.\n"
            + "=" * 44
        )
    return (
        "=== REX EXPOSURE_BLOCK DIRECTIVE ===\n"
        "  REX has explicitly cleared exposure — book is not over-extended. "
        "Normal sizing rules apply.\n"
        + "=" * 44
    )
