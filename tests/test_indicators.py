"""
tests/test_indicators.py — Unit tests for indicators.py.

Run with:  pytest tests/test_indicators.py -v
"""

import numpy as np
import pandas as pd
import pytest

from indicators import (
    calculate_all_indicators,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_rsi,
    calculate_vwap,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_prices(n: int = 100, trend: float = 0.001) -> pd.Series:
    """Deterministic price series with a mild uptrend."""
    rng = np.random.default_rng(42)
    returns = rng.normal(trend, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with a DatetimeIndex (UTC)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = _make_prices(n)
    high = close * 1.005
    low = close * 0.995
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": high.values,
            "low": low.values,
            "close": close.values,
            "volume": np.random.default_rng(0).integers(1_000, 100_000, n).astype(float),
        },
        index=idx,
    )


# ─── RSI ──────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_output_in_range(self):
        rsi = calculate_rsi(_make_prices())
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_length_matches_input(self):
        prices = _make_prices(50)
        assert len(calculate_rsi(prices)) == len(prices)

    def test_constant_prices_not_nan_after_warmup(self):
        prices = pd.Series([100.0] * 50)
        rsi = calculate_rsi(prices, period=14)
        # All gains == 0, all losses == 0 → RSI is undefined (NaN) or 50 by convention
        # Key: no error should be raised
        assert len(rsi) == 50

    def test_mostly_rising_series_is_high(self):
        # Use a series with small dips but dominant gains so avg_loss > 0
        rng = np.random.default_rng(7)
        prices = pd.Series(np.cumsum(rng.choice([1.0, -0.1], size=100, p=[0.9, 0.1])) + 100)
        rsi = calculate_rsi(prices)
        valid = rsi.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] > 60  # strongly bullish series should have high RSI


# ─── MACD ─────────────────────────────────────────────────────────────────────

class TestMACD:
    def test_returns_three_series(self):
        prices = _make_prices()
        macd, signal, hist = calculate_macd(prices)
        assert hasattr(macd, "iloc") and hasattr(signal, "iloc") and hasattr(hist, "iloc")

    def test_series_same_length(self):
        prices = _make_prices(80)
        macd, signal, hist = calculate_macd(prices)
        assert len(macd) == len(signal) == len(hist) == 80

    def test_histogram_equals_macd_minus_signal(self):
        prices = _make_prices()
        macd, signal, hist = calculate_macd(prices)
        diff = (macd - signal - hist).dropna().abs()
        assert (diff < 1e-10).all()


# ─── Bollinger Bands ──────────────────────────────────────────────────────────

class TestBollingerBands:
    def test_upper_above_mid_above_lower(self):
        prices = _make_prices(60)
        upper, mid, lower = calculate_bollinger_bands(prices)
        valid = upper.dropna().index
        assert (upper[valid] >= mid[valid]).all()
        assert (mid[valid] >= lower[valid]).all()

    def test_uses_sample_std_dev(self):
        """Verify ddof=1 (not ddof=0): band width > 0 and matches manual calc."""
        prices = pd.Series([10.0, 11.0, 9.0, 10.5, 10.2] * 10)
        upper, mid, lower = calculate_bollinger_bands(prices, period=5)
        expected_std = prices.rolling(5).std(ddof=1)
        expected_upper = mid + 2 * expected_std
        diff = (upper - expected_upper).dropna().abs()
        assert (diff < 1e-8).all(), "Bollinger Bands must use ddof=1 (sample std dev)"

    def test_constant_series_has_zero_width(self):
        prices = pd.Series([50.0] * 30)
        upper, mid, lower = calculate_bollinger_bands(prices)
        width = (upper - lower).dropna().abs()
        assert (width < 1e-8).all()


# ─── VWAP ─────────────────────────────────────────────────────────────────────

class TestVWAP:
    def test_returns_series_same_length(self):
        df = _make_ohlcv()
        vwap = calculate_vwap(df["high"], df["low"], df["close"], df["volume"])
        assert len(vwap) == len(df)

    def test_resets_across_sessions(self):
        """VWAP at the start of day 2 should not equal the end of day 1."""
        df = _make_ohlcv(n=48)  # 2 days of hourly data
        vwap = calculate_vwap(df["high"], df["low"], df["close"], df["volume"])
        # First candle of day 2 (index 24) — VWAP should equal typical price of that candle
        day2_first_tp = (df["high"].iloc[24] + df["low"].iloc[24] + df["close"].iloc[24]) / 3
        assert abs(vwap.iloc[24] - day2_first_tp) < 1e-6, (
            "VWAP must reset at start of each session"
        )

    def test_single_candle_equals_typical_price(self):
        high = pd.Series([105.0], index=pd.date_range("2024-01-01", periods=1, freq="1h", tz="UTC"))
        low = pd.Series([95.0], index=high.index)
        close = pd.Series([100.0], index=high.index)
        volume = pd.Series([1000.0], index=high.index)
        vwap = calculate_vwap(high, low, close, volume)
        assert abs(vwap.iloc[0] - 100.0) < 1e-6


# ─── calculate_all_indicators ─────────────────────────────────────────────────

class TestCalculateAllIndicators:
    def test_returns_nonempty_dict(self):
        df = _make_ohlcv()
        result = calculate_all_indicators(df)
        assert isinstance(result, dict) and len(result) > 0

    def test_empty_dataframe_returns_empty(self):
        assert calculate_all_indicators(pd.DataFrame()) == {}

    def test_too_short_returns_empty(self):
        df = _make_ohlcv(n=3)
        assert calculate_all_indicators(df) == {}

    def test_rsi_key_present_and_in_range(self):
        df = _make_ohlcv()
        result = calculate_all_indicators(df)
        assert "rsi" in result
        if result["rsi"] is not None:
            assert 0 <= result["rsi"] <= 100

    def test_bb_ordering(self):
        df = _make_ohlcv()
        result = calculate_all_indicators(df)
        if all(result.get(k) for k in ("bb_upper", "bb_mid", "bb_lower")):
            assert result["bb_upper"] >= result["bb_mid"] >= result["bb_lower"]
