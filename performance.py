"""
performance.py — Track record reporting, open-position updating,
and AI-powered lookback analysis with persistent memory injection.
"""

import logging
import re
import sqlite3
from collections import Counter
from typing import Dict, List, Optional, Any

import anthropic

from tracker import (
    get_analyst_performance,
    get_open_recommendations,
    get_recommendations_history,
    save_lookback_memory,
    update_analyst_stats,
)
from data_fetcher import fetch_coingecko_price
from config import ANALYST_ORDER, DB_PATH, PORTFOLIO_SIZE

logger = logging.getLogger(__name__)


# ─── Exposure & Correlation Analysis ─────────────────────────────────────────


def _compute_exposure_analysis(
    positions: List[Dict[str, Any]],
) -> str:
    """Analyze portfolio-level concentration risk across open positions.
    Detects: same-asset pileups, conflicting directions, net directional exposure.
    """
    if not positions:
        return ""

    # Group by symbol
    by_symbol: Dict[str, List[Dict]] = {}
    for p in positions:
        by_symbol.setdefault(p.get("symbol", "?"), []).append(p)

    lines = ["\n⚖️  EXPOSURE & CORRELATION ANALYSIS", "-" * 52]

    for sym, pos_list in sorted(by_symbol.items()):
        longs = [p for p in pos_list if p.get("recommendation", "").upper() == "LONG"]
        shorts = [p for p in pos_list if p.get("recommendation", "").upper() == "SHORT"]
        long_analysts = [p["analyst"] for p in longs]
        short_analysts = [p["analyst"] for p in shorts]

        # Net exposure
        long_usd = sum(p.get("position_size_usd") or 0 for p in longs)
        short_usd = sum(p.get("position_size_usd") or 0 for p in shorts)
        net_usd = long_usd - short_usd

        lines.append(f"\n  {sym}: {len(longs)}L / {len(shorts)}S ({len(pos_list)} total)")

        # Concentration warning: 3+ analysts same direction
        if len(longs) >= 3:
            lines.append(
                f"    ⚠️  CONCENTRATED LONG: {', '.join(long_analysts)} all long {sym}"
                f" — this is one large directional bet, not 3 independent calls"
            )
        if len(shorts) >= 3:
            lines.append(
                f"    ⚠️  CONCENTRATED SHORT: {', '.join(short_analysts)} all short {sym}"
            )

        # Conflicting directions
        if longs and shorts:
            lines.append(
                f"    ⚠️  CONFLICTING: {', '.join(long_analysts)} LONG vs "
                f"{', '.join(short_analysts)} SHORT — hedging into irrelevance"
            )

        # Sizing
        if long_usd or short_usd:
            pct_of_port = abs(net_usd) / PORTFOLIO_SIZE * 100 if PORTFOLIO_SIZE else 0
            direction = "LONG" if net_usd > 0 else "SHORT" if net_usd < 0 else "FLAT"
            lines.append(
                f"    Net exposure: {direction} ${abs(net_usd):,.0f} "
                f"({pct_of_port:.1f}% of portfolio)"
            )

    # Overall portfolio concentration
    all_symbols = list(by_symbol.keys())
    total_positions = sum(len(v) for v in by_symbol.values())
    if len(all_symbols) == 1 and total_positions > 2:
        lines.append(
            f"\n    🔴 SINGLE-ASSET CONCENTRATION: All {total_positions} positions "
            f"are in {all_symbols[0]}. Zero diversification."
        )

    return "\n".join(lines)


def _compute_exposure_for_history(history: List[Dict]) -> str:
    """Analyze historical concurrent position overlap from closed+open calls.
    Identifies periods where multiple analysts had the same directional bet.
    """
    if not history:
        return ""

    # Find groups of calls open at the same time on the same symbol
    by_symbol: Dict[str, List[Dict]] = {}
    for r in history:
        by_symbol.setdefault(r.get("symbol", "?"), []).append(r)

    warnings = []
    for sym, calls in by_symbol.items():
        longs = [c for c in calls if c.get("recommendation", "").upper() == "LONG"]
        shorts = [c for c in calls if c.get("recommendation", "").upper() == "SHORT"]

        if len(longs) >= 3:
            analysts = list({c["analyst"] for c in longs})
            warnings.append(
                f"- CONCENTRATED LONG on {sym}: {len(longs)} simultaneous long calls "
                f"by {', '.join(analysts)} — portfolio treated this as one large bet"
            )
        if len(shorts) >= 3:
            analysts = list({c["analyst"] for c in shorts})
            warnings.append(
                f"- CONCENTRATED SHORT on {sym}: {len(shorts)} simultaneous short calls "
                f"by {', '.join(analysts)}"
            )
        if longs and shorts:
            l_names = list({c["analyst"] for c in longs})
            s_names = list({c["analyst"] for c in shorts})
            warnings.append(
                f"- CONFLICTING on {sym}: {', '.join(l_names)} were LONG while "
                f"{', '.join(s_names)} were SHORT simultaneously"
            )

    if not warnings:
        return ""

    return "=== CORRELATION & EXPOSURE ISSUES ===\n" + "\n".join(warnings)


# ─── Open Position Updater ────────────────────────────────────────────────────


def update_open_recommendations() -> List[Dict[str, Any]]:
    """
    Fetch current prices for all open recommendations and compute
    unrealised P&L. Flags positions where stop or target has been hit.

    Returns a list of enriched dicts (does NOT write to DB — caller decides).
    """
    open_recs = get_open_recommendations()
    if not open_recs:
        return []

    # Batch price fetches (one CoinGecko call per unique symbol)
    symbols = list({r["symbol"] for r in open_recs})
    price_cache: Dict[str, Optional[float]] = {}
    for sym in symbols:
        data = fetch_coingecko_price(sym)
        price_cache[sym] = data.get("price")

    enriched = []
    for rec in open_recs:
        sym = rec["symbol"]
        current_price = price_cache.get(sym)
        if current_price is None or not rec.get("entry_price"):
            continue

        entry = rec["entry_price"]
        direction = rec["recommendation"]

        if direction == "LONG":
            pct = (current_price - entry) / entry * 100
        elif direction == "SHORT":
            pct = (entry - current_price) / entry * 100
        else:
            pct = (current_price - entry) / entry * 100

        # Flag automatically breached levels (does not auto-close them)
        status_note = ""
        if direction == "LONG":
            if rec.get("stop_loss") and current_price <= rec["stop_loss"]:
                status_note = "STOP_HIT"
            elif rec.get("target_price") and current_price >= rec["target_price"]:
                status_note = "TARGET_HIT"
        elif direction == "SHORT":
            if rec.get("stop_loss") and current_price >= rec["stop_loss"]:
                status_note = "STOP_HIT"
            elif rec.get("target_price") and current_price <= rec["target_price"]:
                status_note = "TARGET_HIT"

        enriched.append(
            {
                "id": rec["id"],
                "analyst": rec["analyst"],
                "symbol": sym,
                "recommendation": direction,
                "entry_price": entry,
                "target_price": rec.get("target_price"),
                "stop_loss": rec.get("stop_loss"),
                "current_price": current_price,
                "current_pct": round(pct, 2),
                "status_note": status_note,
                "timestamp": rec.get("timestamp", "")[:10],
                "confidence": rec.get("confidence"),
                "thesis": rec.get("thesis", ""),
            }
        )

    return enriched


# ─── Performance Report ───────────────────────────────────────────────────────


def generate_performance_report() -> str:
    """Build a text performance report for all analysts.
    Stats are derived directly from the database.
    """
    # Refresh stats for all analysts before displaying
    for analyst in ANALYST_ORDER:
        update_analyst_stats(analyst)

    stats_rows = {s["analyst"]: s for s in get_analyst_performance()}
    open_positions = update_open_recommendations()

    lines = ["\n📊  ANALYST PERFORMANCE REPORT", "=" * 52]

    for analyst in ANALYST_ORDER:
        s = stats_rows.get(analyst, {})
        total = s.get("total_calls", 0)
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
        avg_return = (
            round(s.get("total_return_pct", 0.0) / total, 2) if total > 0 else 0.0
        )
        best = s.get("best_call_pct", 0.0) or 0.0
        worst = s.get("worst_call_pct", 0.0) or 0.0

        lines.append(f"\n  [{analyst}]")
        if total == 0:
            lines.append("    No closed calls yet.")
        else:
            lines.append(
                f"    Closed: {total}  |  Win rate: {win_rate}%  |  "
                f"Avg return: {avg_return:+.2f}%"
            )
            lines.append(
                f"    Best call: {best:+.2f}%  |  Worst call: {worst:+.2f}%"
            )

    # Open positions section
    if open_positions:
        lines.append(f"\n📂  OPEN POSITIONS ({len(open_positions)})")
        lines.append("-" * 52)
        for p in open_positions:
            pct = p["current_pct"]
            sign = "+" if pct >= 0 else ""
            note = f"  ← {p['status_note']}" if p["status_note"] else ""
            entry_fmt = (
                f"${p['entry_price']:,.4f}"
                if p["entry_price"] < 1
                else f"${p['entry_price']:,.2f}"
            )
            cur_fmt = (
                f"${p['current_price']:,.4f}"
                if p["current_price"] < 1
                else f"${p['current_price']:,.2f}"
            )
            lines.append(
                f"  {p['analyst']:6} | {p['symbol']:6} {p['recommendation']:7} "
                f"@ {entry_fmt} → {cur_fmt} ({sign}{pct:.1f}%){note}"
            )
    else:
        lines.append("\n  No open positions tracked.")

    # Exposure analysis across open positions
    if open_positions:
        exposure = _compute_exposure_analysis(open_positions)
        if exposure:
            lines.append(exposure)

    return "\n".join(lines)


# ─── Lookback Analysis ────────────────────────────────────────────────────────


def generate_lookback_report(
    symbol: str,
    days: int,
    client: anthropic.Anthropic,
    model: str = "claude-sonnet-4-6",
) -> str:
    """
    Retrieve past recommendations for `symbol` over `days` days, then ask
    Claude to synthesise lessons learned. Saves the result to the DB so it
    can be prepended to future analyst system prompts.

    Returns the plain-text summary.
    """
    history = get_recommendations_history(symbol=symbol, days=days)

    if not history:
        msg = f"No recommendations found for {symbol.upper()} in the past {days} days."
        logger.info(msg)
        return msg

    # Build a concise textual summary of past calls for the prompt
    call_lines = []
    for r in history:
        outcome = (
            f"{r['outcome_pct']:+.1f}%"
            if r.get("outcome_pct") is not None
            else "OPEN"
        )
        entry = (
            f"${r['entry_price']:,.4f}"
            if r.get("entry_price") and r["entry_price"] < 1
            else (f"${r['entry_price']:,.2f}" if r.get("entry_price") else "N/A")
        )
        call_lines.append(
            f"[{r['timestamp'][:10]}] {r['analyst']:6} — {r['recommendation']:7} "
            f"{r['symbol']} @ {entry}  conf={r.get('confidence', '?')}/10  "
            f"status={r['status']} ({outcome})\n"
            f"  Thesis: {(r.get('thesis') or '')[:250]}"
        )

    calls_text = "\n\n".join(call_lines)

    # Compute exposure/correlation issues for the lookback period
    exposure_text = _compute_exposure_for_history(history)

    # Lookback v2 augmentations (2026-04-20) — price context, thesis dispersion,
    # and an honest check on whether last week's lessons were actually attempted.
    price_context = compute_price_context(history)
    dispersion = compute_thesis_dispersion(history)
    lessons_attempted = compute_lessons_attempted(symbol, days)

    prompt = f"""You are a senior trading coach reviewing past analyst calls for {symbol.upper()} over the last {days} days.

=== PRICE CONTEXT ===
{price_context}

=== CALL HISTORY ===
{calls_text}

{exposure_text}

=== THESIS DISPERSION ===
{dispersion}

=== LESSONS ATTEMPTED — DID LAST WEEK'S FINDINGS CHANGE BEHAVIOR? ===
{lessons_attempted}

Produce a concise post-mortem with these five sections:

**KEY PATTERNS** — What conditions or signals correlated with accurate calls? Tie to the PRICE CONTEXT above — was the market a trend, chop, or reversal?
**FAILURES** — Where did analysts get it wrong and what did they miss?
**POSITION SIZING & CORRELATION** — Did multiple analysts pile into the same direction simultaneously? If so, the portfolio had concentrated directional exposure disguised as independent calls. Flag any periods where 3+ analysts were long or short the same asset at once. Note any conflicting positions (simultaneous long AND short from different analysts on the same coin).
**LESSONS LEARNED** — 3–5 specific, actionable lessons for future {symbol.upper()} analysis. Each lesson must be concrete and testable.
**BIAS WATCH** — Any systematic team-wide biases to guard against (groupthink, confirmation bias, directional herding)? Use the THESIS DISPERSION data above to quantify groupthink — if avg cluster similarity is >0.40 that is textbook rubber-stamping. Call it out numerically. Also address the LESSONS ATTEMPTED block — name which prior lessons the team respected and which it ignored.

Be specific. Reference actual calls above. Bullet points only. Under 500 words total.
This output will be prepended to each analyst's system prompt as persistent memory."""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text
    except Exception as e:
        logger.error("Lookback Claude call failed: %s", e)
        summary = f"[Lookback generation failed: {e}]"

    # Persist and refresh stats
    save_lookback_memory(symbol, days, summary)
    for analyst in ANALYST_ORDER:
        update_analyst_stats(analyst)

    return summary


# ─── Lookback v2 helpers (2026-04-20) ─────────────────────────────────────────
#
# These augment generate_lookback_report with context that the prior format
# was missing: price action framing, a quantitative groupthink measure, and
# an honest accounting of whether last week's prescribed lessons changed this
# week's behavior. They are pure-Python (no external deps) and read-only
# against the recommendations table.


def compute_price_context(history: List[Dict[str, Any]]) -> str:
    """
    Summarize price action over the lookback window using entry prices from
    actual calls as a cheap proxy for OHLC when we have enough rows. This
    avoids pulling a separate OHLC feed just for the lookback. Returns a short
    plain-text block.
    """
    entries = [
        r for r in history
        if r.get("entry_price") and r["entry_price"] > 0
    ]
    if len(entries) < 3:
        return "Insufficient entry-price data in window to summarize price context."

    # Sort by timestamp ascending so first/last represent start/end of window.
    entries.sort(key=lambda r: r.get("timestamp") or "")
    prices = [r["entry_price"] for r in entries]
    first_px = prices[0]
    last_px = prices[-1]
    hi = max(prices)
    lo = min(prices)
    ret_pct = (last_px - first_px) / first_px * 100 if first_px else 0.0
    range_pct = (hi - lo) / lo * 100 if lo else 0.0

    # Regime label based on return+range (coarse but useful framing).
    if ret_pct > 5 and range_pct < 15:
        regime = "steady uptrend"
    elif ret_pct < -5 and range_pct < 15:
        regime = "steady downtrend"
    elif abs(ret_pct) < 3 and range_pct > 10:
        regime = "high-volatility chop (no clear direction)"
    elif ret_pct > 5 and range_pct >= 15:
        regime = "volatile uptrend (whipsaw risk)"
    elif ret_pct < -5 and range_pct >= 15:
        regime = "volatile downtrend (whipsaw risk)"
    else:
        regime = "range-bound"

    fmt = (
        "${:,.4f}".format if first_px < 1 else "${:,.2f}".format
    )
    return (
        f"Window entry prices: first {fmt(first_px)} → last {fmt(last_px)} "
        f"(net {ret_pct:+.2f}%)\n"
        f"Intra-window extremes: {fmt(lo)} / {fmt(hi)} (range {range_pct:.1f}%)\n"
        f"Regime label: {regime}"
    )


_WORD_RE = re.compile(r"[a-z0-9]{3,}")
# Stopwords specific to crypto analyst prose — these are the words that pop
# up in every thesis regardless of direction and would inflate similarity
# scores artificially.
_STOP = frozenset({
    "the", "and", "for", "with", "into", "that", "this", "have", "has", "but",
    "was", "are", "not", "from", "price", "level", "call", "long", "short",
    "watch", "avoid", "neutral", "bullish", "bearish", "above", "below",
    "trade", "setup", "entry", "target", "stop", "support", "resistance",
    "market", "analyst", "current", "over", "under", "past", "week", "near",
    "strong", "weak", "risk", "reward", "size", "position", "confidence",
})


def _thesis_tokens(text: str) -> set:
    if not text:
        return set()
    return {
        w for w in _WORD_RE.findall(text.lower())
        if w not in _STOP
    }


def compute_thesis_dispersion(history: List[Dict[str, Any]]) -> str:
    """
    Quantify how similar analyst theses are when multiple analysts go the
    same direction within the same hour. High avg similarity = rubber-stamping.

    Uses Jaccard similarity on content-word tokens (no ML deps). A block
    ranges from fully independent (0.00) to identical prose (1.00). Empirical
    guidance from the 4/20 lookback: avg cluster similarity ≥0.40 indicates
    the team is rephrasing one thesis, not producing eleven.
    """
    if len(history) < 6:
        return "Too few rows in window to compute dispersion reliably."

    # Group by (hour, symbol, direction)
    clusters: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in history:
        ts = (r.get("timestamp") or "")[:13]  # YYYY-MM-DDTHH
        sym = (r.get("symbol") or "?").upper()
        d = (r.get("recommendation") or "").upper()
        if d not in ("LONG", "SHORT") or not ts:
            continue
        clusters.setdefault((ts, sym, d), []).append(r)

    big_clusters = {k: v for k, v in clusters.items() if len(v) >= 3}
    if not big_clusters:
        return (
            "No hours in this window had 3+ analysts aligned on the same "
            "direction — no groupthink clusters to measure."
        )

    similarities: List[float] = []
    example_lines: List[str] = []

    for (ts, sym, direction), rows in sorted(big_clusters.items()):
        token_sets = [_thesis_tokens(r.get("thesis") or "") for r in rows]
        # Average pairwise Jaccard
        n = len(token_sets)
        pair_scores: List[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                a, b = token_sets[i], token_sets[j]
                if not a and not b:
                    continue
                union = a | b
                if not union:
                    continue
                pair_scores.append(len(a & b) / len(union))
        if not pair_scores:
            continue
        avg_sim = sum(pair_scores) / len(pair_scores)
        similarities.append(avg_sim)
        if len(example_lines) < 3 or avg_sim >= 0.50:
            analysts = [r.get("analyst", "?") for r in rows]
            example_lines.append(
                f"  [{ts}] {sym} {direction} — {n} analysts "
                f"({', '.join(analysts)}): avg_sim={avg_sim:.2f}"
            )

    if not similarities:
        return "No measurable thesis content in clustered calls."

    overall = sum(similarities) / len(similarities)
    if overall >= 0.40:
        label = "HIGH (groupthink — analysts are rephrasing one thesis)"
    elif overall >= 0.25:
        label = "MODERATE (some overlap, but distinct lenses visible)"
    else:
        label = "LOW (theses are genuinely independent)"

    lines = [
        f"Overall avg cluster thesis similarity: {overall:.2f} — {label}",
        f"Clusters measured: {len(similarities)} (3+ analyst same-direction same-hour)",
    ]
    if example_lines:
        lines.append("Examples:")
        lines.extend(example_lines[:5])
    return "\n".join(lines)


def compute_lessons_attempted(symbol: str, days: int) -> str:
    """
    Compare the current window's structural KPIs against the window
    immediately preceding it. The goal is to surface whether the team
    attempted to heed last week's lessons (direction balance, confidence
    discipline, cluster intensity) — not just repeat the same mistakes.

    If there is no prior lookback memory, returns a short "baseline" note.
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        current = cur.execute(
            """
            SELECT recommendation, confidence, outcome_pct
            FROM recommendations
            WHERE symbol = ?
              AND timestamp >= datetime('now', ?)
            """,
            (symbol.upper(), f"-{days} days"),
        ).fetchall()

        prior = cur.execute(
            """
            SELECT recommendation, confidence, outcome_pct
            FROM recommendations
            WHERE symbol = ?
              AND timestamp >= datetime('now', ?)
              AND timestamp <  datetime('now', ?)
            """,
            (symbol.upper(), f"-{2 * days} days", f"-{days} days"),
        ).fetchall()

        # Whether we have any prior lookback memory to reference.
        prior_memory = cur.execute(
            """
            SELECT generated_at FROM lookback_memory
            WHERE symbol = ? AND generated_at < datetime('now', ?)
            ORDER BY generated_at DESC LIMIT 1
            """,
            (symbol.upper(), f"-{days // 2 if days >= 2 else 1} days"),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("compute_lessons_attempted read failed: %s", exc)
        return f"[Lessons-attempted diff unavailable: {exc}]"
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not current:
        return "No calls in current window — nothing to compare."

    def _summarize(rows: List[sqlite3.Row]) -> Dict[str, Any]:
        n = len(rows)
        longs = sum(1 for r in rows if (r["recommendation"] or "").upper() == "LONG")
        shorts = sum(1 for r in rows if (r["recommendation"] or "").upper() == "SHORT")
        closed = [r for r in rows if r["outcome_pct"] is not None]
        wins = sum(1 for r in closed if r["outcome_pct"] > 0)
        high_conf = [
            r for r in rows
            if (r["confidence"] or 0) >= 7 and (r["recommendation"] or "").upper() in ("LONG", "SHORT")
        ]
        return {
            "n": n,
            "longs": longs,
            "shorts": shorts,
            "long_pct": round(longs / n * 100, 1) if n else 0.0,
            "closed": len(closed),
            "wins": wins,
            "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
            "high_conf_count": len(high_conf),
            "high_conf_share": round(len(high_conf) / n * 100, 1) if n else 0.0,
        }

    cur_s = _summarize(current)
    prior_s = _summarize(prior) if prior else None

    if not prior_s:
        return (
            f"Current window: {cur_s['n']} calls | LONG share {cur_s['long_pct']}% | "
            f"win rate {cur_s['win_rate']}% | high-conf share {cur_s['high_conf_share']}%\n"
            "No prior-window data available for comparison — this is the baseline."
        )

    def _delta(cur: float, prev: float) -> str:
        d = cur - prev
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.1f}"

    lines = [
        f"Prior window ({days}d before current):",
        f"  calls={prior_s['n']}, LONG share={prior_s['long_pct']}%, "
        f"win_rate={prior_s['win_rate']}%, high_conf_share={prior_s['high_conf_share']}%",
        f"Current window ({days}d):",
        f"  calls={cur_s['n']}, LONG share={cur_s['long_pct']}%, "
        f"win_rate={cur_s['win_rate']}%, high_conf_share={cur_s['high_conf_share']}%",
        f"Deltas:",
        f"  LONG share: {_delta(cur_s['long_pct'], prior_s['long_pct'])} pp  "
        f"(if prior week prescribed 'reduce LONG bias', want negative)",
        f"  win rate:   {_delta(cur_s['win_rate'], prior_s['win_rate'])} pp  "
        f"(positive = lessons helping)",
        f"  high-conf share: {_delta(cur_s['high_conf_share'], prior_s['high_conf_share'])} pp  "
        f"(prior lookback recommended capping overconfidence — want negative)",
    ]
    if prior_memory:
        lines.append(f"Prior lookback memory generated: {prior_memory['generated_at'][:19]}")
    else:
        lines.append(
            "No prior lookback memory row exists for this symbol in the preceding period "
            "— team had no memorialized lessons to work from."
        )
    return "\n".join(lines)
