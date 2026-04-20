"""
tests/test_guardrails.py — Unit tests for the pre-prompt guardrails module.

Covers compute_exposure, find_recent_closed_losses,
get_confidence_calibration, build_guardrail_block,
parse_rex_exposure_block, and render_rex_block_note.

Uses a temporary SQLite DB per test via monkeypatch, mirroring the
pattern in test_tracker.py — no test ever touches recommendations.db.
"""

from datetime import datetime, timedelta, timezone

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated SQLite for tracker + guardrails."""
    # Redirect DB_PATH BEFORE importing modules that capture it.
    import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "gr.db")

    import tracker
    import guardrails
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "gr.db")
    monkeypatch.setattr(guardrails, "DB_PATH", tmp_path / "gr.db")
    tracker.init_db()
    return {"tracker": tracker, "guardrails": guardrails}


def _iso_hours_ago(hours: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _insert_row(
    tracker, *, analyst, symbol, rec, entry, conf, outcome_pct=None, status="OPEN",
    size_usd=None, thesis="t", closed_at=None, timestamp=None,
):
    """Low-level insert that lets us backdate timestamps."""
    import sqlite3
    with sqlite3.connect(tracker.DB_PATH, timeout=5) as conn:
        conn.execute(
            """
            INSERT INTO recommendations
              (timestamp, analyst, symbol, recommendation, entry_price,
               target_price, stop_loss, confidence, thesis, status,
               outcome_pct, closed_at, position_size_usd)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp or _iso_hours_ago(0.1),
                analyst, symbol.upper(), rec.upper(), entry,
                conf, thesis, status, outcome_pct, closed_at, size_usd,
            ),
        )
        conn.commit()


# ─── compute_exposure ─────────────────────────────────────────────────────────


class TestComputeExposure:
    def test_empty_db_returns_zeroes(self, db):
        snap = db["guardrails"].compute_exposure("BTC")
        assert snap.symbol == "BTC"
        assert snap.long_count == 0
        assert snap.short_count == 0
        assert snap.long_usd == 0.0
        assert snap.short_pct_of_portfolio == 0.0

    def test_counts_only_open_rows(self, db):
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=7, size_usd=2000, status="OPEN")
        _insert_row(db["tracker"], analyst="NOVA", symbol="BTC", rec="LONG",
                    entry=70000, conf=5, size_usd=1000, status="CLOSED",
                    outcome_pct=-1.0, closed_at=_iso_hours_ago(2))
        snap = db["guardrails"].compute_exposure("BTC")
        assert snap.long_count == 1
        assert snap.long_usd == 2000
        assert "ARIA" in snap.long_analysts
        assert "NOVA" not in snap.long_analysts

    def test_short_and_long_split(self, db):
        _insert_row(db["tracker"], analyst="ARIA", symbol="ETH", rec="LONG",
                    entry=2000, conf=6, size_usd=500)
        _insert_row(db["tracker"], analyst="ZEN", symbol="ETH", rec="SHORT",
                    entry=2000, conf=6, size_usd=800)
        snap = db["guardrails"].compute_exposure("ETH")
        assert snap.long_count == 1 and snap.short_count == 1
        assert snap.long_usd == 500 and snap.short_usd == 800

    def test_pct_of_portfolio_math(self, db):
        # $12,400 long = exactly 10% of default $124,000 portfolio.
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=7, size_usd=12400)
        snap = db["guardrails"].compute_exposure("BTC")
        assert abs(snap.long_pct_of_portfolio - 10.0) < 0.01


# ─── find_recent_closed_losses ───────────────────────────────────────────────


class TestFindRecentClosedLosses:
    def test_returns_only_losses_within_window(self, db):
        # A loss 2h ago on BTC — within default 12h window
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=6, status="CLOSED", outcome_pct=-2.1,
                    closed_at=_iso_hours_ago(2), size_usd=1000)
        # A loss 30h ago — outside the window
        _insert_row(db["tracker"], analyst="NOVA", symbol="BTC", rec="LONG",
                    entry=70000, conf=5, status="CLOSED", outcome_pct=-1.5,
                    closed_at=_iso_hours_ago(30), size_usd=1000)
        # A WIN 1h ago — should not appear
        _insert_row(db["tracker"], analyst="MARCUS", symbol="BTC", rec="LONG",
                    entry=70000, conf=6, status="CLOSED", outcome_pct=+3.2,
                    closed_at=_iso_hours_ago(1), size_usd=1000)

        hits = db["guardrails"].find_recent_closed_losses("BTC", hours=12)
        assert len(hits) == 1
        assert hits[0].analyst == "ARIA"
        assert hits[0].outcome_pct == -2.1
        assert 1.5 < hits[0].hours_ago < 2.5

    def test_no_losses_returns_empty(self, db):
        assert db["guardrails"].find_recent_closed_losses("SOL") == []


# ─── get_confidence_calibration ──────────────────────────────────────────────


class TestConfidenceCalibration:
    def test_below_min_sample_ignored(self, db):
        # Only 2 rows at conf=7 — below CALIBRATION_MIN_N (4) so excluded.
        for _ in range(2):
            _insert_row(db["tracker"], analyst="ARIA", symbol="BTC",
                        rec="LONG", entry=70000, conf=7,
                        status="CLOSED", outcome_pct=+1.0,
                        closed_at=_iso_hours_ago(5), timestamp=_iso_hours_ago(10))
        calib = db["guardrails"].get_confidence_calibration("ARIA", "BTC", days=30)
        assert 7 not in calib

    def test_bucket_computed_correctly(self, db):
        pcts = [+1.0, -0.5, +2.0, -3.0, +4.0]  # 3 wins, 2 losses → 60% win-rate
        for p in pcts:
            _insert_row(db["tracker"], analyst="ARIA", symbol="BTC",
                        rec="LONG", entry=70000, conf=6,
                        status="CLOSED", outcome_pct=p,
                        closed_at=_iso_hours_ago(5), timestamp=_iso_hours_ago(10))
        calib = db["guardrails"].get_confidence_calibration("ARIA", "BTC", days=30)
        assert 6 in calib
        assert calib[6]["n"] == 5
        assert calib[6]["wins"] == 3
        assert calib[6]["win_rate"] == 0.6

    def test_only_includes_closed_positions(self, db):
        # 4 CLOSED at conf=5, 3 OPEN at conf=5 — calibration should see 4.
        for p in [+1, -1, +2, -2]:
            _insert_row(db["tracker"], analyst="MARCUS", symbol="ETH",
                        rec="LONG", entry=2000, conf=5,
                        status="CLOSED", outcome_pct=p,
                        closed_at=_iso_hours_ago(5), timestamp=_iso_hours_ago(10))
        for _ in range(3):
            _insert_row(db["tracker"], analyst="MARCUS", symbol="ETH",
                        rec="LONG", entry=2000, conf=5, status="OPEN",
                        timestamp=_iso_hours_ago(1))
        calib = db["guardrails"].get_confidence_calibration("MARCUS", "ETH", days=30)
        assert calib[5]["n"] == 4


# ─── build_guardrail_block ───────────────────────────────────────────────────


class TestBuildGuardrailBlock:
    def test_empty_db_returns_empty_string(self, db):
        block = db["guardrails"].build_guardrail_block("ARIA", "BTC")
        assert block == ""

    def test_exposure_warn_triggers_block(self, db):
        # Open $15,000 long on BTC — 12% of portfolio, above WARN (10%).
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=7, size_usd=15000)
        block = db["guardrails"].build_guardrail_block("MARCUS", "BTC")
        assert "OPEN BOOK EXPOSURE" in block
        assert "12.1%" in block or "12.0%" in block
        # Not yet at CAP (15%) so no "HARD CAP" text
        assert "HARD CAP" not in block

    def test_exposure_hard_cap_triggers_downgrade_language(self, db):
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=7, size_usd=20000)  # ~16%
        block = db["guardrails"].build_guardrail_block("MARCUS", "BTC")
        assert "HARD CAP" in block
        assert "downgrade to WATCH" in block

    def test_cooldown_block_appears_for_recent_loss(self, db):
        _insert_row(db["tracker"], analyst="ARIA", symbol="ETH", rec="LONG",
                    entry=2000, conf=7, status="CLOSED", outcome_pct=-3.5,
                    closed_at=_iso_hours_ago(4), size_usd=1000)
        block = db["guardrails"].build_guardrail_block("MARCUS", "ETH")
        assert "RECENT CLOSED LOSSES" in block
        assert "-3.5%" in block

    def test_calibration_block_appears_for_own_history(self, db):
        # ARIA has 5 closed conf-6 LONGs on RPL with mixed outcomes.
        for p in [+2.0, -1.0, +3.0, -2.0, +1.0]:
            _insert_row(db["tracker"], analyst="ARIA", symbol="RPL",
                        rec="LONG", entry=1.8, conf=6, status="CLOSED",
                        outcome_pct=p, closed_at=_iso_hours_ago(6),
                        timestamp=_iso_hours_ago(12))
        block = db["guardrails"].build_guardrail_block("ARIA", "RPL")
        assert "CONFIDENCE CALIBRATION" in block
        assert "ARIA" in block
        assert "conf=6" in block

    def test_calibration_is_per_analyst(self, db):
        # ARIA's history should not leak into MARCUS's calibration block.
        for p in [+1.0, -1.0, +2.0, -2.0]:
            _insert_row(db["tracker"], analyst="ARIA", symbol="RPL",
                        rec="LONG", entry=1.8, conf=6, status="CLOSED",
                        outcome_pct=p, closed_at=_iso_hours_ago(6),
                        timestamp=_iso_hours_ago(12))
        marcus_block = db["guardrails"].build_guardrail_block("MARCUS", "RPL")
        # MARCUS has no calibration data of his own, but ARIA's exposure
        # isn't triggered either (no open rows) — so block should be empty.
        assert "CONFIDENCE CALIBRATION" not in marcus_block

    def test_include_flags_disable_sections(self, db):
        _insert_row(db["tracker"], analyst="ARIA", symbol="BTC", rec="LONG",
                    entry=70000, conf=7, size_usd=20000)  # hard-cap exposure
        block = db["guardrails"].build_guardrail_block(
            "MARCUS", "BTC",
            include_exposure=False, include_cooldown=False, include_calibration=False,
        )
        assert block == ""


# ─── REX directive parser ────────────────────────────────────────────────────


class TestParseRexExposureBlock:
    def test_parses_yes(self, db):
        resp = "Book is concentrated.\nEXPOSURE_BLOCK: YES\n[SIGNAL: WATCH | ...]"
        assert db["guardrails"].parse_rex_exposure_block(resp) is True

    def test_parses_no_case_insensitive(self, db):
        resp = "We have room.\nexposure_block: no\n[SIGNAL: LONG | ...]"
        assert db["guardrails"].parse_rex_exposure_block(resp) is False

    def test_missing_directive_returns_none(self, db):
        resp = "No directive emitted. [SIGNAL: WATCH]"
        assert db["guardrails"].parse_rex_exposure_block(resp) is None

    def test_empty_string_returns_none(self, db):
        assert db["guardrails"].parse_rex_exposure_block("") is None

    def test_render_rex_block_note_yes(self, db):
        note = db["guardrails"].render_rex_block_note(True)
        assert "declared the book over-exposed" in note
        assert "downgrade to WATCH" in note

    def test_render_rex_block_note_no(self, db):
        note = db["guardrails"].render_rex_block_note(False)
        assert "explicitly cleared exposure" in note
