"""
tests/test_data_fetcher.py — Unit tests for data_fetcher.py pure functions.

These tests cover only the local, side-effect-free functions (no network calls).

Run with:  pytest tests/test_data_fetcher.py -v
"""

import pytest

from data_fetcher import compute_order_book_imbalance, get_coingecko_id


# ─── compute_order_book_imbalance ─────────────────────────────────────────────

class TestComputeOrderBookImbalance:
    def test_equal_bids_asks_is_zero(self):
        ob = {"bids": [["100", "5"], ["99", "5"]], "asks": [["101", "5"], ["102", "5"]]}
        result = compute_order_book_imbalance(ob)
        assert result == 0.0

    def test_bid_heavy_is_positive(self):
        ob = {"bids": [["100", "8"]], "asks": [["101", "2"]]}
        result = compute_order_book_imbalance(ob)
        # bids=8, asks=2, total=10 → (8-2)/10*100 = 60%
        assert abs(result - 60.0) < 0.01

    def test_ask_heavy_is_negative(self):
        ob = {"bids": [["100", "2"]], "asks": [["101", "8"]]}
        result = compute_order_book_imbalance(ob)
        assert abs(result - (-60.0)) < 0.01

    def test_empty_dict_returns_none(self):
        assert compute_order_book_imbalance({}) is None

    def test_none_returns_none(self):
        assert compute_order_book_imbalance(None) is None

    def test_empty_bids_and_asks_returns_zero_or_none(self):
        ob = {"bids": [], "asks": []}
        # total == 0, should return 0.0 (not raise)
        result = compute_order_book_imbalance(ob)
        assert result in (0.0, None)

    def test_malformed_quantity_returns_none(self):
        # b[1] is the quantity; malformed quantity should trigger exception handling
        ob = {"bids": [["100", "not_a_number"]], "asks": [["101", "5"]]}
        result = compute_order_book_imbalance(ob)
        assert result is None

    def test_result_is_rounded_to_one_decimal(self):
        ob = {"bids": [["100", "1"]], "asks": [["101", "2"]]}
        result = compute_order_book_imbalance(ob)
        assert result is not None
        assert result == round(result, 1)


# ─── get_coingecko_id ─────────────────────────────────────────────────────────

class TestGetCoingeckoId:
    @pytest.mark.parametrize("symbol,expected", [
        ("BTC",    "bitcoin"),
        ("ETH",    "ethereum"),
        ("SOL",    "solana"),
        ("DOGE",   "dogecoin"),
        ("MATIC",  "matic-network"),
        ("btc",    "bitcoin"),  # lowercase input
        ("Eth",    "ethereum"),  # mixed case
    ])
    def test_known_symbols(self, symbol, expected):
        assert get_coingecko_id(symbol) == expected

    def test_unknown_symbol_lowercases(self):
        # Unknown symbols fall back to lowercase of the input
        assert get_coingecko_id("UNKNOWN123") == "unknown123"

    def test_all_config_symbols_are_mapped(self):
        """Ensure config.SYMBOL_TO_CG_ID and data_fetcher both use the same map."""
        from config import SYMBOL_TO_CG_ID
        for symbol, cg_id in SYMBOL_TO_CG_ID.items():
            assert get_coingecko_id(symbol) == cg_id
