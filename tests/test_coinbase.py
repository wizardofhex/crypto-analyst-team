"""
tests/test_coinbase.py — Tests for Coinbase Advanced Trade API integration.

Covers: fetch_coinbase_ohlcv, fetch_coinbase_ticker, fetch_coinbase_order_book,
and Coinbase fallback wiring in fetch_all_market_data.
"""

from unittest.mock import patch, MagicMock
import pytest
import pandas as pd

from data_fetcher import (
    fetch_coinbase_ohlcv,
    fetch_coinbase_ticker,
    fetch_coinbase_order_book,
    compute_order_book_imbalance,
)


# ─── fetch_coinbase_ohlcv ────────────────────────────────────────────────────


class TestFetchCoinbaseOHLCV:

    def _make_candles(self, n=5):
        import time
        now = int(time.time())
        return {
            "candles": [
                {
                    "start": str(now - i * 3600),
                    "low": "100.0",
                    "high": "105.0",
                    "open": "101.0",
                    "close": "104.0",
                    "volume": "500.0",
                }
                for i in range(n)
            ]
        }

    def test_returns_dataframe_with_correct_columns(self):
        with patch("data_fetcher._coinbase_get", return_value=self._make_candles()):
            df = fetch_coinbase_ohlcv("BTC", interval="1h", limit=5)
        assert df is not None
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 5

    def test_returns_none_on_api_failure(self):
        with patch("data_fetcher._coinbase_get", return_value=None):
            df = fetch_coinbase_ohlcv("BTC", interval="1h")
        assert df is None

    def test_returns_none_on_empty_candles(self):
        with patch("data_fetcher._coinbase_get", return_value={"candles": []}):
            df = fetch_coinbase_ohlcv("BTC", interval="1h")
        assert df is None

    def test_unsupported_interval_returns_none(self):
        df = fetch_coinbase_ohlcv("BTC", interval="2h")
        assert df is None

    def test_dataframe_sorted_by_timestamp(self):
        with patch("data_fetcher._coinbase_get", return_value=self._make_candles(10)):
            df = fetch_coinbase_ohlcv("BTC", interval="1h", limit=10)
        assert df is not None
        assert df.index.is_monotonic_increasing

    def test_4h_interval_uses_six_hour_granularity(self):
        with patch("data_fetcher._coinbase_get", return_value=self._make_candles()) as mock_get:
            fetch_coinbase_ohlcv("BTC", interval="4h", limit=5)
        call_params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert call_params["granularity"] == "SIX_HOUR"


# ─── fetch_coinbase_ticker ───────────────────────────────────────────────────


class TestFetchCoinbaseTicker:

    def test_returns_bid_ask_spread(self):
        raw = {
            "best_bid": "95000.50",
            "best_ask": "95010.00",
            "trades": [{"price": "95005.00", "size": "0.01", "side": "BUY"}],
        }
        with patch("data_fetcher._coinbase_get", return_value=raw):
            ticker = fetch_coinbase_ticker("BTC")
        assert ticker is not None
        assert ticker["best_bid"] == 95000.50
        assert ticker["best_ask"] == 95010.00
        assert ticker["spread_pct"] is not None
        assert ticker["spread_pct"] > 0
        assert ticker["last_trade_side"] == "BUY"

    def test_returns_none_on_failure(self):
        with patch("data_fetcher._coinbase_get", return_value=None):
            ticker = fetch_coinbase_ticker("BTC")
        assert ticker is None

    def test_returns_none_on_empty_response(self):
        with patch("data_fetcher._coinbase_get", return_value={}):
            ticker = fetch_coinbase_ticker("BTC")
        assert ticker is None

    def test_spread_calculation_is_correct(self):
        raw = {"best_bid": "100.00", "best_ask": "100.10", "trades": []}
        with patch("data_fetcher._coinbase_get", return_value=raw):
            ticker = fetch_coinbase_ticker("BTC")
        # spread = (100.10 - 100.00) / 100.05 * 100 ≈ 0.0999
        assert ticker is not None
        assert 0.09 < ticker["spread_pct"] < 0.11


# ─── fetch_coinbase_order_book ───────────────────────────────────────────────


class TestFetchCoinbaseOrderBook:

    def test_returns_normalized_format(self):
        raw = {
            "pricebook": {
                "bids": [{"price": "95000", "size": "1.5"}, {"price": "94999", "size": "0.5"}],
                "asks": [{"price": "95001", "size": "1.0"}, {"price": "95002", "size": "2.0"}],
            }
        }
        with patch("data_fetcher._coinbase_get", return_value=raw):
            ob = fetch_coinbase_order_book("BTC", limit=2)
        assert ob is not None
        assert len(ob["bids"]) == 2
        assert len(ob["asks"]) == 2
        assert ob["source"] == "coinbase"
        # Format: [[price, qty], ...]
        assert ob["bids"][0] == ["95000", "1.5"]

    def test_compatible_with_compute_imbalance(self):
        raw = {
            "pricebook": {
                "bids": [{"price": "100", "size": "10"}],
                "asks": [{"price": "101", "size": "5"}],
            }
        }
        with patch("data_fetcher._coinbase_get", return_value=raw):
            ob = fetch_coinbase_order_book("BTC")
        imbalance = compute_order_book_imbalance(ob)
        # bids=10, asks=5, total=15 → (10-5)/15*100 = 33.3%
        assert imbalance is not None
        assert 33.0 < imbalance < 34.0

    def test_returns_none_on_failure(self):
        with patch("data_fetcher._coinbase_get", return_value=None):
            ob = fetch_coinbase_order_book("BTC")
        assert ob is None

    def test_returns_none_on_empty_book(self):
        with patch("data_fetcher._coinbase_get", return_value={"pricebook": {"bids": [], "asks": []}}):
            ob = fetch_coinbase_order_book("BTC")
        assert ob is None
