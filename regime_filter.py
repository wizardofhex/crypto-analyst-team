"""
regime_filter.py — v2 plan (2026-05-02): no-setup precondition gate
                    + six-state market regime classifier.

The gate is consulted at the top of run_scheduled_analysis.py per coin
BEFORE the 11-analyst loop. If no trigger fires, we skip the analyst
loop entirely and tag the run no-setup-skip. The lookbacks identified
mid-range chop trading as the worst-performing trade type; this gate
prevents the team from being asked to find a trade where there isn't one.

The classifier returns one of six labels that get injected into every
analyst prompt so analysts can adapt their reasoning to the regime.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from indicators import calculate_all_indicators, calculate_atr

logger = logging.getLogger(__name__)


# ─── Regime labels ────────────────────────────────────────────────────────────

REGIME_LABELS = (
    "STRONG_UPTREND",
    "STRONG_DOWNTREND",
    "HIGH_VOL_EXPANSION",
    "LOW_VOL_CONTRACTION",
    "RANGE_BOUND_MID",
    "BREAKOUT_EXHAUSTION",
)


# ─── No-setup precondition gate ───────────────────────────────────────────────

def has_setup(symbol: str, market_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Decide whether the LLM analyst loop should run on this coin.

    Returns (should_run, reason). reason is a comma-joined list of triggers
    that fired (e.g. 'vol_expanding,near_200ema'); if no trigger fires the
    reason is 'no-setup' and should_run is False.

    Triggers (any one fires):
      - vol_expanding: 4h ATR ratio > 1.3x its 20-bar mean
      - near_200ema: price within 1 ATR of EMA-200 (4h)
      - near_week_high / near_week_low: price within 1 ATR of 7d high/low
      - funding_extreme: |funding_rate| > 0.05% (0.0005)
      - sentiment_extreme: F&G <= 25 or >= 75
      - big_move_24h: |24h pct change| > 2x ATR%

    On data failures (e.g. CoinGecko rate-limited, no OHLCV) we DEFAULT TO
    True with reason 'data-incomplete' so the team still runs — better to
    over-run than miss a real setup because of a failed API call.
    """
    triggers = []

    cg = market_data.get("coingecko") or {}
    price: Optional[float] = cg.get("price")

    ohlcv = market_data.get("ohlcv") or {}
    df_4h = ohlcv.get("4h")

    # Need a 4h dataframe to compute regime context. If missing, default-pass.
    if df_4h is None or df_4h.empty or len(df_4h) < 30 or price is None:
        return True, "data-incomplete"

    try:
        ind = calculate_all_indicators(df_4h, timeframe="4h") or {}
    except Exception as exc:
        logger.warning("has_setup: indicators failed for %s: %s", symbol, exc)
        return True, "data-incomplete"

    atr = ind.get("atr")
    ema_200 = ind.get("ema_200")

    # vol_expanding: 4h ATR vs its 20-bar rolling mean
    try:
        atr_series = calculate_atr(df_4h["high"], df_4h["low"], df_4h["close"])
        atr_20 = atr_series.tail(20).mean()
        if atr and atr_20 and atr_20 > 0 and atr / atr_20 > 1.3:
            triggers.append("vol_expanding")
    except Exception:
        pass

    # near_200ema: price within 1 ATR of EMA-200
    if atr and ema_200 and abs(price - ema_200) <= atr:
        triggers.append("near_200ema")

    # near_week_high / near_week_low: 7d range proximity
    try:
        # 4h candles, 42 bars = 7 days
        recent = df_4h.tail(42)
        wk_high = float(recent["high"].max())
        wk_low = float(recent["low"].min())
        if atr and abs(price - wk_high) <= atr:
            triggers.append("near_week_high")
        if atr and abs(price - wk_low) <= atr:
            triggers.append("near_week_low")
    except Exception:
        pass

    # funding_extreme: 0.05% threshold
    funding = market_data.get("funding_rate")
    if funding is not None and abs(funding) > 0.0005:
        triggers.append("funding_extreme")

    # sentiment_extreme: F&G <= 25 or >= 75
    fg = (market_data.get("fear_greed") or {}).get("value")
    if isinstance(fg, (int, float)) and (fg <= 25 or fg >= 75):
        triggers.append("sentiment_extreme")

    # big_move_24h: |24h pct change| > 2x ATR%
    chg_24h = cg.get("change_24h")
    if chg_24h is not None and atr and price and price > 0:
        atr_pct = (atr / price) * 100.0
        if atr_pct > 0 and abs(chg_24h) > 2.0 * atr_pct:
            triggers.append("big_move_24h")

    if triggers:
        return True, ",".join(triggers)
    return False, "no-setup"


# ─── Six-state regime classifier ──────────────────────────────────────────────

def classify_regime(symbol: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify the current market regime for a single coin.

    Returns a dict with:
      label:         one of REGIME_LABELS, or 'UNKNOWN' if data missing
      ema_200_dist:  % distance from EMA-200 (signed)
      atr_ratio:     current ATR / 20-bar mean ATR
      bb_width_pct:  Bollinger Band width as % of price
      rsi:           RSI(14) value
      change_7d:     7-day % change
      reasoning:     short string explaining the label
    """
    out: Dict[str, Any] = {
        "label": "UNKNOWN",
        "ema_200_dist": None,
        "atr_ratio": None,
        "bb_width_pct": None,
        "rsi": None,
        "change_7d": None,
        "reasoning": "no data",
    }

    cg = market_data.get("coingecko") or {}
    price: Optional[float] = cg.get("price")
    ohlcv = market_data.get("ohlcv") or {}
    df_4h = ohlcv.get("4h")
    if df_4h is None or df_4h.empty or len(df_4h) < 50 or price is None:
        return out

    try:
        ind = calculate_all_indicators(df_4h, timeframe="4h") or {}
        atr = ind.get("atr")
        ema_200 = ind.get("ema_200")
        bb_upper = ind.get("bb_upper")
        bb_lower = ind.get("bb_lower")
        rsi = ind.get("rsi")
        chg_7d = cg.get("change_7d")

        atr_ratio = None
        try:
            atr_series = calculate_atr(df_4h["high"], df_4h["low"], df_4h["close"])
            atr_20 = float(atr_series.tail(20).mean())
            if atr and atr_20 > 0:
                atr_ratio = round(atr / atr_20, 2)
        except Exception:
            atr_20 = None

        ema_200_dist = (
            round((price - ema_200) / ema_200 * 100, 2)
            if ema_200 and ema_200 > 0
            else None
        )
        bb_width_pct = (
            round((bb_upper - bb_lower) / price * 100, 2)
            if bb_upper and bb_lower and price > 0
            else None
        )

        out.update({
            "ema_200_dist": ema_200_dist,
            "atr_ratio": atr_ratio,
            "bb_width_pct": bb_width_pct,
            "rsi": rsi,
            "change_7d": chg_7d,
        })

        # ── Decision tree (order matters: highest specificity first) ──
        # BREAKOUT_EXHAUSTION: extreme RSI or BB%B
        bb_pct_b = ind.get("bb_pct_b")
        if rsi is not None and (rsi > 75 or rsi < 25):
            out["label"] = "BREAKOUT_EXHAUSTION"
            out["reasoning"] = f"RSI={rsi} extreme"
            return out
        if bb_pct_b is not None and (bb_pct_b > 95 or bb_pct_b < 5):
            out["label"] = "BREAKOUT_EXHAUSTION"
            out["reasoning"] = f"BB%B={bb_pct_b} extreme"
            return out

        # HIGH_VOL_EXPANSION
        if atr_ratio is not None and atr_ratio > 1.5:
            out["label"] = "HIGH_VOL_EXPANSION"
            out["reasoning"] = f"ATR ratio={atr_ratio}x (>1.5x)"
            return out

        # LOW_VOL_CONTRACTION
        if atr_ratio is not None and atr_ratio < 0.7:
            out["label"] = "LOW_VOL_CONTRACTION"
            out["reasoning"] = f"ATR ratio={atr_ratio}x (<0.7x)"
            return out

        # STRONG_UPTREND / STRONG_DOWNTREND: 200 EMA + 7d move
        if ema_200_dist is not None and ema_200_dist > 3.0 and (chg_7d or 0) > 5.0:
            out["label"] = "STRONG_UPTREND"
            out["reasoning"] = f"price {ema_200_dist:+.1f}% vs EMA200, 7d {chg_7d:+.1f}%"
            return out
        if ema_200_dist is not None and ema_200_dist < -3.0 and (chg_7d or 0) < -5.0:
            out["label"] = "STRONG_DOWNTREND"
            out["reasoning"] = f"price {ema_200_dist:+.1f}% vs EMA200, 7d {chg_7d:+.1f}%"
            return out

        # Default: RANGE_BOUND_MID
        out["label"] = "RANGE_BOUND_MID"
        out["reasoning"] = (
            f"RSI={rsi}, ATR ratio={atr_ratio}, "
            f"EMA200 dist={ema_200_dist}%"
        )
        return out

    except Exception as exc:
        logger.warning("classify_regime failed for %s: %s", symbol, exc)
        out["reasoning"] = f"classifier error: {exc}"
        return out


def regime_block(regime: Dict[str, Any]) -> str:
    """Format a regime classification result as a prompt-injection block."""
    label = regime.get("label", "UNKNOWN")

    implication = {
        "STRONG_UPTREND": (
            "Trend continuation has highest hit rate. Be willing to LONG on pullbacks "
            "to EMA support; fade short setups unless catalyst is concrete."
        ),
        "STRONG_DOWNTREND": (
            "Trend continuation has highest hit rate. Be willing to SHORT on relief rallies; "
            "fade long setups unless capitulation pattern is present."
        ),
        "HIGH_VOL_EXPANSION": (
            "Wide ranges, fast moves. Use wider stops (2x ATR), expect breakouts both ways. "
            "Fade extremes only with confluence."
        ),
        "LOW_VOL_CONTRACTION": (
            "Compression precedes expansion. Be patient; trend trades have low edge until "
            "ATR expands. Default toward WATCH unless an extreme catalyst is in view."
        ),
        "RANGE_BOUND_MID": (
            "MID-RANGE WARNING: this regime is the team's documented worst-performer (mid-range "
            "trend-continuation lost money repeatedly in the 4/20 and 5/2 lookbacks). "
            "Be highly skeptical of trend-following calls. Default toward WATCH unless "
            "you can cite exceptional confluence (volume + structure + level + sentiment)."
        ),
        "BREAKOUT_EXHAUSTION": (
            "Mean-reversion edge is highest here (capitulation longs, blow-off shorts). "
            "Use confirmation candles (volume + body) before entering."
        ),
        "UNKNOWN": (
            "Regime data unavailable; reason about the tape directly without leaning on regime."
        ),
    }.get(label, "")

    lines = [
        "=== MARKET REGIME ===",
        f"Coin regime: {label}",
    ]
    if regime.get("rsi") is not None:
        lines.append(f"RSI(14):       {regime['rsi']}")
    if regime.get("atr_ratio") is not None:
        lines.append(f"ATR ratio:     {regime['atr_ratio']}x  (1.0 = baseline)")
    if regime.get("ema_200_dist") is not None:
        lines.append(f"vs EMA-200:    {regime['ema_200_dist']:+.2f}%")
    if regime.get("bb_width_pct") is not None:
        lines.append(f"BB width:      {regime['bb_width_pct']}% of price")
    if regime.get("change_7d") is not None:
        lines.append(f"7d change:     {regime['change_7d']:+.2f}%")
    lines.append(f"Implication:   {implication}")
    lines.append("=" * 24)

    return "\n".join(lines)
