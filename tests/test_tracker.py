"""
tests/test_tracker.py — Unit tests for tracker.py.

Uses a temporary SQLite database so tests never touch recommendations.db.

Run with:  pytest tests/test_tracker.py -v
"""

from pathlib import Path

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    """Import tracker with DB_PATH redirected to a fresh temp file per test."""
    import tracker as t
    monkeypatch.setattr(t, "DB_PATH", tmp_path / "test.db")
    t.init_db()
    return t


# ─── save_recommendation ──────────────────────────────────────────────────────

class TestSaveRecommendation:
    def test_returns_integer_id(self, tracker):
        rec_id = tracker.save_recommendation(
            analyst="ARIA",
            symbol="BTC",
            recommendation="LONG",
            entry_price=50000.0,
            target_price=55000.0,
            stop_loss=48000.0,
            confidence=7,
            thesis="Breakout above resistance.",
        )
        assert isinstance(rec_id, int) and rec_id > 0

    def test_invalid_recommendation_raises(self, tracker):
        with pytest.raises(ValueError, match="Invalid recommendation"):
            tracker.save_recommendation(
                analyst="REX",
                symbol="ETH",
                recommendation="YOLO",
                entry_price=None,
                target_price=None,
                stop_loss=None,
                confidence=5,
                thesis="",
            )

    def test_confidence_clamped_to_1_10(self, tracker):
        rec_id = tracker.save_recommendation(
            analyst="ZEN",
            symbol="SOL",
            recommendation="NEUTRAL",
            entry_price=None,
            target_price=None,
            stop_loss=None,
            confidence=99,  # should be clamped to 10
            thesis="Testing clamp.",
        )
        rows = tracker.get_open_recommendations("SOL")
        assert rows[0]["confidence"] == 10

    def test_case_insensitive_recommendation(self, tracker):
        rec_id = tracker.save_recommendation(
            analyst="NOVA",
            symbol="BNB",
            recommendation="short",  # lowercase
            entry_price=300.0,
            target_price=250.0,
            stop_loss=320.0,
            confidence=6,
            thesis="Distribution pattern.",
        )
        rows = tracker.get_open_recommendations("BNB")
        assert rows[0]["recommendation"] == "SHORT"


# ─── get_recommendations_history ──────────────────────────────────────────────

class TestGetRecommendationsHistory:
    def test_returns_saved_records(self, tracker):
        tracker.save_recommendation("ARIA", "BTC", "LONG", 50000.0, None, None, 7, "Test")
        history = tracker.get_recommendations_history(symbol="BTC")
        assert len(history) == 1
        assert history[0]["symbol"] == "BTC"

    def test_empty_when_no_records(self, tracker):
        history = tracker.get_recommendations_history(symbol="XRP")
        assert history == []

    def test_filters_by_analyst(self, tracker):
        tracker.save_recommendation("ARIA",   "ETH", "LONG",  2000.0, None, None, 7, "A")
        tracker.save_recommendation("MARCUS", "ETH", "SHORT", 2000.0, None, None, 5, "B")
        history = tracker.get_recommendations_history(symbol="ETH", analyst="ARIA")
        assert all(r["analyst"] == "ARIA" for r in history)

    def test_days_filter_excludes_other_symbols(self, tracker):
        tracker.save_recommendation("REX", "DOGE", "AVOID", None, None, None, 3, "Test")
        tracker.save_recommendation("REX", "BTC",  "LONG",  None, None, None, 5, "Test")
        # Filtering by DOGE should not return BTC records
        history = tracker.get_recommendations_history(symbol="DOGE", days=30)
        assert all(r["symbol"] == "DOGE" for r in history)


# ─── close_recommendation ─────────────────────────────────────────────────────

class TestCloseRecommendation:
    def test_long_profit(self, tracker):
        rec_id = tracker.save_recommendation(
            "ARIA", "BTC", "LONG", 50000.0, 55000.0, 48000.0, 8, "Trend trade"
        )
        outcome = tracker.close_recommendation(rec_id, close_price=55000.0)
        assert abs(outcome - 10.0) < 0.01  # (55000-50000)/50000 * 100 = 10%

    def test_short_profit(self, tracker):
        rec_id = tracker.save_recommendation(
            "MARCUS", "ETH", "SHORT", 3000.0, 2700.0, 3150.0, 6, "Distribution"
        )
        outcome = tracker.close_recommendation(rec_id, close_price=2700.0)
        # (3000-2700)/3000*100 = 10% profit for SHORT
        assert abs(outcome - 10.0) < 0.01

    def test_long_loss(self, tracker):
        rec_id = tracker.save_recommendation(
            "ZEN", "SOL", "LONG", 100.0, 120.0, 90.0, 5, "Reversal"
        )
        outcome = tracker.close_recommendation(rec_id, close_price=90.0)
        assert outcome < 0

    def test_record_not_found_returns_none(self, tracker):
        result = tracker.close_recommendation(9999, close_price=100.0)
        assert result is None

    def test_invalid_status_raises(self, tracker):
        rec_id = tracker.save_recommendation(
            "NOVA", "ADA", "WATCH", None, None, None, 4, ""
        )
        with pytest.raises(ValueError, match="Invalid status"):
            tracker.close_recommendation(rec_id, close_price=1.0, status="BADSTATUS")

    def test_updates_analyst_stats_automatically(self, tracker):
        """close_recommendation should trigger update_analyst_stats (AUD-009 fix)."""
        rec_id = tracker.save_recommendation(
            "REX", "LINK", "LONG", 10.0, 12.0, 9.0, 7, "Stats test"
        )
        tracker.close_recommendation(rec_id, close_price=12.0)
        stats = tracker.get_analyst_performance("REX")
        assert len(stats) == 1
        assert stats[0]["total_calls"] == 1
        assert stats[0]["wins"] == 1
