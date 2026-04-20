"""
tests/test_lookback_v2.py — Unit tests for the lookback v2 helpers added
to performance.py on 2026-04-20: compute_price_context,
compute_thesis_dispersion, compute_lessons_attempted.

These helpers are pure-Python and operate on recommendation dicts /
the recommendations table. They have no external deps and return plain text.
"""

from datetime import datetime, timedelta, timezone

import pytest


def _iso_hours_ago(hours: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%S+00:00")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pv2.db")

    import tracker
    import performance
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "pv2.db")
    monkeypatch.setattr(performance, "DB_PATH", tmp_path / "pv2.db")
    tracker.init_db()
    return {"tracker": tracker, "performance": performance}


def _raw_insert(tracker, **kw):
    import sqlite3
    with sqlite3.connect(tracker.DB_PATH, timeout=5) as conn:
        conn.execute(
            """
            INSERT INTO recommendations
              (timestamp, analyst, symbol, recommendation, entry_price,
               target_price, stop_loss, confidence, thesis, status,
               outcome_pct, closed_at)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
            """,
            (
                kw["timestamp"], kw["analyst"], kw["symbol"].upper(),
                kw["rec"].upper(), kw.get("entry"), kw.get("conf"),
                kw.get("thesis", "t"), kw.get("status", "OPEN"),
                kw.get("outcome_pct"), kw.get("closed_at"),
            ),
        )
        conn.commit()


# ─── compute_price_context ───────────────────────────────────────────────────


class TestPriceContext:
    def test_too_few_rows_returns_insufficient(self, db):
        out = db["performance"].compute_price_context([])
        assert "Insufficient" in out

    def test_labels_steady_uptrend(self, db):
        history = [
            {"timestamp": _iso_hours_ago(72), "entry_price": 100.0},
            {"timestamp": _iso_hours_ago(48), "entry_price": 104.0},
            {"timestamp": _iso_hours_ago(24), "entry_price": 107.0},
            {"timestamp": _iso_hours_ago(1),  "entry_price": 108.0},
        ]
        out = db["performance"].compute_price_context(history)
        assert "steady uptrend" in out
        assert "+8.00%" in out

    def test_labels_chop(self, db):
        history = [
            {"timestamp": _iso_hours_ago(72), "entry_price": 100.0},
            {"timestamp": _iso_hours_ago(60), "entry_price": 112.0},
            {"timestamp": _iso_hours_ago(48), "entry_price": 95.0},
            {"timestamp": _iso_hours_ago(24), "entry_price": 105.0},
            {"timestamp": _iso_hours_ago(1),  "entry_price": 101.0},
        ]
        out = db["performance"].compute_price_context(history)
        # +1% return, ~18% range → high-volatility chop
        assert "chop" in out


# ─── compute_thesis_dispersion ───────────────────────────────────────────────


class TestThesisDispersion:
    def test_too_few_rows(self, db):
        out = db["performance"].compute_thesis_dispersion([{"timestamp": "x"}])
        assert "Too few" in out

    def test_no_clusters(self, db):
        history = [
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "a b c", "analyst": "ARIA"},
            {"timestamp": "2026-04-20T02:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "d e f", "analyst": "NOVA"},
            {"timestamp": "2026-04-20T03:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "g h i", "analyst": "MARCUS"},
            {"timestamp": "2026-04-20T04:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "j k l", "analyst": "DELTA"},
            {"timestamp": "2026-04-20T05:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "m n o", "analyst": "QUANT"},
            {"timestamp": "2026-04-20T06:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "p q r", "analyst": "REX"},
        ]
        out = db["performance"].compute_thesis_dispersion(history)
        assert "No hours" in out

    def test_high_similarity_cluster(self, db):
        # 6+ rows required by the helper. Build one 4-person cluster
        # with nearly-identical theses + 2 filler singletons in other hours.
        thesis = (
            "whale accumulation bitcoin bullish breakout resistance confluence macd "
            "cross rising momentum"
        )
        history = [
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": thesis, "analyst": "ARIA"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": thesis, "analyst": "NOVA"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": thesis, "analyst": "MARCUS"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": thesis, "analyst": "DELTA"},
            {"timestamp": "2026-04-20T02:00", "symbol": "BTC",
             "recommendation": "WATCH", "thesis": "wait", "analyst": "QUANT"},
            {"timestamp": "2026-04-20T03:00", "symbol": "BTC",
             "recommendation": "WATCH", "thesis": "wait", "analyst": "ATLAS"},
        ]
        out = db["performance"].compute_thesis_dispersion(history)
        assert "HIGH" in out or "groupthink" in out
        assert "avg_sim=1.00" in out or "avg_sim=0.9" in out

    def test_low_similarity_cluster(self, db):
        # 6+ rows, one 4-person cluster with distinct content words per thesis.
        history = [
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "macd histogram nine twenty-one crossover",
             "analyst": "ARIA"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "wallet accumulation exchange outflow cohort",
             "analyst": "CHAIN"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "sentiment index twenty-two extreme reading",
             "analyst": "NOVA"},
            {"timestamp": "2026-04-20T01:00", "symbol": "BTC",
             "recommendation": "LONG", "thesis": "options gamma magnet seventy-two strike",
             "analyst": "VEGA"},
            {"timestamp": "2026-04-20T02:00", "symbol": "BTC",
             "recommendation": "WATCH", "thesis": "wait", "analyst": "QUANT"},
            {"timestamp": "2026-04-20T03:00", "symbol": "BTC",
             "recommendation": "WATCH", "thesis": "wait", "analyst": "ATLAS"},
        ]
        out = db["performance"].compute_thesis_dispersion(history)
        assert "LOW" in out or "MODERATE" in out


# ─── compute_lessons_attempted ───────────────────────────────────────────────


class TestLessonsAttempted:
    def test_no_data_returns_empty_note(self, db):
        out = db["performance"].compute_lessons_attempted("BTC", days=7)
        assert "No calls" in out or "baseline" in out or "unavailable" in out

    def test_baseline_when_no_prior(self, db):
        # Current window only — should report baseline
        _raw_insert(db["tracker"], timestamp=_iso_hours_ago(2),
                    analyst="ARIA", symbol="BTC", rec="LONG", entry=70000, conf=7)
        _raw_insert(db["tracker"], timestamp=_iso_hours_ago(10),
                    analyst="NOVA", symbol="BTC", rec="LONG", entry=70000, conf=5)
        out = db["performance"].compute_lessons_attempted("BTC", days=7)
        assert "baseline" in out.lower() or "Prior window" not in out

    def test_delta_computation_when_prior_exists(self, db):
        # Prior week: 4 calls, 100% LONG
        for i in range(4):
            _raw_insert(
                db["tracker"],
                timestamp=_iso_hours_ago(24 * 10 + i),
                analyst="ARIA", symbol="ETH", rec="LONG",
                entry=2000, conf=7, status="CLOSED", outcome_pct=-2.0,
                closed_at=_iso_hours_ago(24 * 10 + i - 1),
            )
        # Current week: 4 calls, 50% LONG / 50% SHORT
        for rec in ("LONG", "SHORT", "LONG", "SHORT"):
            _raw_insert(
                db["tracker"],
                timestamp=_iso_hours_ago(24 * 2),
                analyst="MARCUS", symbol="ETH", rec=rec,
                entry=2000, conf=5, status="CLOSED", outcome_pct=+1.0,
                closed_at=_iso_hours_ago(24 * 2 - 1),
            )
        out = db["performance"].compute_lessons_attempted("ETH", days=7)
        assert "Prior window" in out
        assert "Current window" in out
        assert "Deltas" in out
