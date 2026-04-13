"""
indicators.py — Pure pandas/numpy technical indicator calculations.
No TA-Lib dependency. Works on any OHLCV DataFrame.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing (EWM)."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, Signal line, and Histogram."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Upper band, middle band (SMA), lower band."""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std(ddof=1)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return prices.ewm(span=period, adjust=False).mean()


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def calculate_stochastic_rsi(
    prices: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> Tuple[pd.Series, pd.Series]:
    """Stochastic RSI — K and D lines (0–100 scale)."""
    rsi = calculate_rsi(prices, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period).max()
    denom = (rsi_max - rsi_min).replace(0, np.nan)
    raw_k = (rsi - rsi_min) / denom * 100
    k = raw_k.rolling(window=k_smooth).mean()
    d = k.rolling(window=d_smooth).mean()
    return k, d


def calculate_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Session-reset VWAP using typical price.

    Resets cumulative sums at midnight UTC so that each calendar date starts
    fresh — matching the conventional intraday VWAP definition.  If the index
    carries no date information (e.g. a plain RangeIndex) the calculation falls
    back to the original cumulative approach.
    """
    typical_price = (high + low + close) / 3
    tp_vol = typical_price * volume

    if hasattr(high.index, "date"):
        # Group by calendar date and cumsum within each group
        dates = pd.Series(high.index).dt.date.values
        cum_tp_vol = tp_vol.groupby(dates).cumsum()
        cum_vol = volume.groupby(dates).cumsum().replace(0, np.nan)
    else:
        cum_tp_vol = tp_vol.cumsum()
        cum_vol = volume.cumsum().replace(0, np.nan)

    return cum_tp_vol / cum_vol


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """Standard pivot points: P, R1-R3, S1-S3."""
    pivot = (high + low + close) / 3
    return {
        "pivot": round(pivot, 4),
        "r1": round(2 * pivot - low, 4),
        "r2": round(pivot + (high - low), 4),
        "r3": round(high + 2 * (pivot - low), 4),
        "s1": round(2 * pivot - high, 4),
        "s2": round(pivot - (high - low), 4),
        "s3": round(low - 2 * (high - pivot), 4),
    }


def calculate_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    return volume.rolling(window=period).mean()


def _safe_last(series: pd.Series, decimals: int = 4) -> Optional[float]:
    """Return the last non-NaN value from a Series, rounded."""
    val = series.dropna()
    if val.empty:
        return None
    return round(float(val.iloc[-1]), decimals)


def _calc_momentum(df, result: dict) -> None:
    close = df["close"]
    rsi = calculate_rsi(close)
    result["rsi"] = _safe_last(rsi, 2)

    macd_line, signal_line, histogram = calculate_macd(close)
    result["macd"] = _safe_last(macd_line, 4)
    result["macd_signal"] = _safe_last(signal_line, 4)
    result["macd_histogram"] = _safe_last(histogram, 4)

    stoch_k, stoch_d = calculate_stochastic_rsi(close)
    result["stoch_rsi_k"] = _safe_last(stoch_k, 2)
    result["stoch_rsi_d"] = _safe_last(stoch_d, 2)


def _calc_bands_and_emas(df, result: dict) -> None:
    close = df["close"]

    bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(close)
    result["bb_upper"] = _safe_last(bb_upper, 4)
    result["bb_mid"] = _safe_last(bb_mid, 4)
    result["bb_lower"] = _safe_last(bb_lower, 4)

    if result["bb_upper"] and result["bb_lower"]:
        bb_range = result["bb_upper"] - result["bb_lower"]
        cur = float(close.iloc[-1])
        result["bb_pct_b"] = (
            round((cur - result["bb_lower"]) / bb_range * 100, 1)
            if bb_range != 0
            else 50.0
        )

    for period in [9, 21, 50, 200]:
        ema = calculate_ema(close, period)
        result[f"ema_{period}"] = _safe_last(ema, 4) if len(close) >= period else None

    for period in [20, 50, 200]:
        if len(close) >= period:
            result[f"sma_{period}"] = _safe_last(
                close.rolling(window=period).mean(), 4
            )

    result["current_price"] = round(float(close.iloc[-1]), 4)
    if len(close) >= 2:
        prev_c = float(close.iloc[-2])
        cur_c = float(close.iloc[-1])
        result["prev_close"] = round(prev_c, 4)
        result["price_change_pct"] = (
            round((cur_c - prev_c) / prev_c * 100, 2) if prev_c != 0 else 0.0
        )

    e9, e21, e50, e200 = (
        result.get("ema_9"),
        result.get("ema_21"),
        result.get("ema_50"),
        result.get("ema_200"),
    )
    if e9 and e21:
        result["ema_9_21_cross"] = "bullish" if e9 > e21 else "bearish"
    if e50 and e200:
        result["golden_cross"] = e50 > e200


def _calc_volume_and_structure(df, result: dict, timeframe: str) -> None:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    result["atr"] = _safe_last(calculate_atr(high, low, close), 4)

    if timeframe in ("4h", "1d"):
        result["vwap"] = None
    else:
        result["vwap"] = _safe_last(calculate_vwap(high, low, close, volume), 4)

    vol_sma = calculate_volume_sma(volume)
    result["volume_sma_20"] = _safe_last(vol_sma, 0)
    if result["volume_sma_20"] and result["volume_sma_20"] > 0:
        result["volume_ratio"] = round(
            float(volume.iloc[-1]) / result["volume_sma_20"] * 100, 1
        )

    if len(df) >= 2:
        prev = df.iloc[-2]
        result["pivots"] = calculate_pivot_points(
            float(prev["high"]), float(prev["low"]), float(prev["close"])
        )


def _calc_candle_info(df, result: dict) -> None:
    if len(df) >= 3:
        last = df.iloc[-1]
        body = abs(float(last["close"]) - float(last["open"]))
        candle_range = float(last["high"]) - float(last["low"])
        if candle_range > 0:
            body_ratio = body / candle_range
            result["last_candle_body_ratio"] = round(body_ratio, 2)
            result["last_candle_is_doji"] = body_ratio < 0.1
            result["last_candle_bullish"] = float(last["close"]) > float(last["open"])


def calculate_all_indicators(df: pd.DataFrame, timeframe: str = "") -> Dict[str, Any]:
    """
    Compute all indicators from an OHLCV DataFrame and return a flat dict
    of the *current* (most-recent candle) values.

    Expected columns: open, high, low, close, volume
    timeframe: optional hint ('15m', '1h', '4h', '1d'). VWAP is omitted for '4h' and '1d'
    since it is meaningless on multi-day candle data.
    """
    if df is None or df.empty or len(df) < 5:
        return {}

    results: Dict[str, Any] = {}
    _calc_momentum(df, results)
    _calc_bands_and_emas(df, results)
    _calc_volume_and_structure(df, results, timeframe)
    _calc_candle_info(df, results)
    return results
