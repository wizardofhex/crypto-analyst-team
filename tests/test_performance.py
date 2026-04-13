"""Tests for the performance module."""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# generate_performance_report
# ---------------------------------------------------------------------------


@patch("performance.update_open_recommendations", return_value=[])
@patch("performance.get_analyst_performance", return_value=[])
@patch("performance.update_analyst_stats")
@patch("performance.ANALYST_ORDER", ["ARIA", "MARCUS"])
def test_generate_performance_report_no_recommendations(
    mock_stats, mock_perf, mock_update
):
    """Report with no data is still a non-empty string."""
    from performance import generate_performance_report

    report = generate_performance_report()
    assert report is not None
    assert len(report) > 0
    assert "PERFORMANCE REPORT" in report


@patch("performance.update_open_recommendations", return_value=[])
@patch(
    "performance.get_analyst_performance",
    return_value=[
        {
            "analyst": "ARIA",
            "total_calls": 5,
            "wins": 3,
            "losses": 2,
            "total_return_pct": 12.5,
            "best_call_pct": 8.0,
            "worst_call_pct": -3.0,
        },
    ],
)
@patch("performance.update_analyst_stats")
@patch("performance.ANALYST_ORDER", ["ARIA"])
def test_generate_performance_report_includes_analyst_names(
    mock_stats, mock_perf, mock_update
):
    """Report includes analyst names from the stats rows."""
    from performance import generate_performance_report

    report = generate_performance_report()
    assert "ARIA" in report
    assert "Win rate" in report


# ---------------------------------------------------------------------------
# update_open_recommendations
# ---------------------------------------------------------------------------


@patch("performance.get_open_recommendations", return_value=[])
def test_update_open_recommendations_no_positions(mock_open):
    """Empty open list returns empty enriched list without error."""
    from performance import update_open_recommendations

    result = update_open_recommendations()
    assert result == []


@patch("performance.fetch_coingecko_price", return_value={"price": 110.0})
@patch(
    "performance.get_open_recommendations",
    return_value=[
        {
            "id": 1,
            "analyst": "MARCUS",
            "symbol": "SOL",
            "recommendation": "LONG",
            "entry_price": 100.0,
            "target_price": 150.0,
            "stop_loss": 90.0,
            "timestamp": "2026-04-01T00:00:00",
            "confidence": 8,
            "thesis": "Bullish breakout",
        }
    ],
)
def test_update_open_recommendations_long_pnl(mock_open, mock_price):
    """LONG position P&L = (current - entry) / entry * 100."""
    from performance import update_open_recommendations

    result = update_open_recommendations()
    assert len(result) == 1
    assert result[0]["current_pct"] == 10.0
    assert result[0]["symbol"] == "SOL"
    assert result[0]["status_note"] == ""


# ---------------------------------------------------------------------------
# generate_lookback_report
# ---------------------------------------------------------------------------


@patch("performance.update_analyst_stats")
@patch("performance.save_lookback_memory")
@patch("performance.get_recommendations_history", return_value=[])
def test_generate_lookback_report_no_history(mock_hist, mock_save, mock_stats):
    """No history returns a message mentioning 'no recommendations'."""
    from performance import generate_lookback_report

    client = MagicMock()
    report = generate_lookback_report("BTC", 30, client)
    assert "No recommendations" in report or "no recommendations" in report.lower()
    client.messages.create.assert_not_called()


@patch("performance.ANALYST_ORDER", ["ARIA"])
@patch("performance.update_analyst_stats")
@patch("performance.save_lookback_memory")
@patch(
    "performance.get_recommendations_history",
    return_value=[
        {
            "timestamp": "2026-03-20T12:00:00",
            "analyst": "ARIA",
            "recommendation": "LONG",
            "symbol": "BTC",
            "entry_price": 65000.0,
            "confidence": 9,
            "status": "CLOSED_TP",
            "outcome_pct": 5.2,
            "thesis": "Strong momentum",
        }
    ],
)
def test_generate_lookback_report_with_history(mock_hist, mock_save, mock_stats):
    """With history, returns the AI-generated summary text."""
    from performance import generate_lookback_report

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Lessons learned summary.")]
    client = MagicMock()
    client.messages.create.return_value = mock_response

    report = generate_lookback_report("BTC", 30, client)
    assert report == "Lessons learned summary."
    client.messages.create.assert_called_once()


@patch("performance.ANALYST_ORDER", ["ARIA"])
@patch("performance.update_analyst_stats")
@patch("performance.save_lookback_memory")
@patch(
    "performance.get_recommendations_history",
    return_value=[
        {
            "timestamp": "2026-03-20T12:00:00",
            "analyst": "ARIA",
            "recommendation": "LONG",
            "symbol": "ETH",
            "entry_price": 3000.0,
            "confidence": 7,
            "status": "OPEN",
            "outcome_pct": None,
            "thesis": "DeFi growth",
        }
    ],
)
def test_generate_lookback_report_uses_correct_model(
    mock_hist, mock_save, mock_stats
):
    """Anthropic client is called with the specified model."""
    from performance import generate_lookback_report

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Analysis.")]
    client = MagicMock()
    client.messages.create.return_value = mock_response

    generate_lookback_report("ETH", 14, client, model="claude-sonnet-4-6")
    call_kwargs = client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"
