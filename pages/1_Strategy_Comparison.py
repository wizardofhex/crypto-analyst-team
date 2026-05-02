"""
pages/1_Strategy_Comparison.py — v2 plan dashboard view.

Three competing strategies plotted side-by-side from 2026-04-04 (DB anchor):
  Strategy A: HODL benchmark (1/3 BTC + 1/3 ETH + 1/3 RPL, fixed since anchor)
  Strategy B: Deterministic rule-based (recommendations_deterministic table)
  Strategy C: LLM Team (recommendations table)

Plus the four pre-mortem hypothesis statuses surfaced as colored cards.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from config import DB_PATH, PORTFOLIO_SIZE, SYMBOL_TO_CG_ID

ANCHOR_DATE = "2026-04-04"
HODL_COINS = ("BTC", "ETH", "RPL")
EM_DASH = "—"

st.set_page_config(page_title="Strategy Comparison · Crypto Analyst Team", layout="wide")

# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════


@st.cache_data(ttl=300)
def fetch_anchor_prices() -> Dict[str, Optional[float]]:
    """Fetch closing prices for HODL coins on ANCHOR_DATE via CoinGecko historical."""
    out: Dict[str, Optional[float]] = {}
    anchor = datetime.fromisoformat(ANCHOR_DATE).replace(tzinfo=timezone.utc)
    date_str = anchor.strftime("%d-%m-%Y")
    for sym in HODL_COINS:
        cg_id = SYMBOL_TO_CG_ID.get(sym)
        if not cg_id:
            out[sym] = None
            continue
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}/history",
                params={"date": date_str, "localization": "false"},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                price = data.get("market_data", {}).get("current_price", {}).get("usd")
                out[sym] = float(price) if price else None
            else:
                out[sym] = None
        except Exception:
            out[sym] = None
    return out


@st.cache_data(ttl=120)
def fetch_current_prices() -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    ids = ",".join(SYMBOL_TO_CG_ID[s] for s in HODL_COINS if s in SYMBOL_TO_CG_ID)
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": "usd"},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            for sym in HODL_COINS:
                cg_id = SYMBOL_TO_CG_ID.get(sym)
                price = data.get(cg_id, {}).get("usd") if cg_id else None
                out[sym] = float(price) if price else None
    except Exception:
        for sym in HODL_COINS:
            out[sym] = None
    return out


def hodl_value(start: float, current: float) -> float:
    """Equal-weight $124K/3 of one coin, marked at current."""
    if not start or start <= 0:
        return PORTFOLIO_SIZE / 3
    units = (PORTFOLIO_SIZE / 3) / start
    return units * (current or start)


def equity_curve_from_table(table: str, anchor_dt: datetime) -> pd.DataFrame:
    """
    Compute a daily equity curve from a recommendations-shaped table.
    Treats each LONG/SHORT signal as a $1,240 (or position_size_usd) bet,
    realizes outcome_pct on close. Open positions are marked at last known
    close price for the symbol.

    Output columns: date (date), equity (float)
    """
    with sqlite3.connect(DB_PATH) as conn:
        # Verify table exists
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not check:
            return pd.DataFrame(columns=["date", "equity"])

        rows = conn.execute(
            f"SELECT timestamp, status, recommendation, entry_price, close_price, "
            f"outcome_pct, position_size_usd, closed_at "
            f"FROM {table} "
            f"WHERE timestamp >= ?",
            (anchor_dt.isoformat(),),
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["date", "equity"])

    cols = ["timestamp", "status", "recommendation", "entry_price",
            "close_price", "outcome_pct", "position_size_usd", "closed_at"]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["closed_at"] = pd.to_datetime(df["closed_at"], errors="coerce", utc=True)

    # For closed rows, we have realized P&L on close_at. Build a daily series.
    closed = df[df["status"].isin(["CLOSED", "EXPIRED"])].copy()
    closed["pnl_usd"] = (
        closed["outcome_pct"].fillna(0) * closed["position_size_usd"].fillna(0) / 100.0
    )
    closed["realize_date"] = closed["closed_at"].dt.date

    # Aggregate daily realized P&L
    daily_realized = closed.groupby("realize_date")["pnl_usd"].sum().sort_index()

    # Build the date range from anchor through today
    start = anchor_dt.date()
    end = datetime.now(timezone.utc).date()
    days = pd.date_range(start, end, freq="D").date
    cum = []
    running = float(PORTFOLIO_SIZE)
    for d in days:
        running += float(daily_realized.get(d, 0.0))
        cum.append({"date": d, "equity": running})

    return pd.DataFrame(cum)


def hodl_curve(anchor_prices: Dict[str, Optional[float]],
               current_prices: Dict[str, Optional[float]]) -> pd.DataFrame:
    """
    Cheap HODL approximation: linear interpolation of equity from anchor (=$124K)
    to today's mark. Good enough for the 28-day window without daily history.
    """
    today = datetime.now(timezone.utc).date()
    start = datetime.fromisoformat(ANCHOR_DATE).date()
    today_value = sum(hodl_value(anchor_prices.get(s) or 0, current_prices.get(s) or 0)
                       for s in HODL_COINS)
    days = pd.date_range(start, today, freq="D").date
    pts = []
    for i, d in enumerate(days):
        frac = i / max(len(days) - 1, 1)
        pts.append({"date": d, "equity": PORTFOLIO_SIZE + (today_value - PORTFOLIO_SIZE) * frac})
    return pd.DataFrame(pts)


def latest_hypothesis_results() -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hypothesis_tests'"
        ).fetchone()
        if not check:
            return []
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT hypothesis, status, metrics, evaluated_at, notes, week_id
            FROM hypothesis_tests
            WHERE (week_id, hypothesis) IN (
              SELECT week_id, hypothesis FROM hypothesis_tests
              GROUP BY hypothesis HAVING MAX(evaluated_at)
            )
            ORDER BY hypothesis
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════════

st.title("Strategy Comparison — v2 Plan")
st.caption(
    f"Three strategies running in parallel since {ANCHOR_DATE}. "
    f"Each starts with a paper portfolio of ${PORTFOLIO_SIZE:,}."
)

# Refresh & anchor row
col_a, col_b, col_c = st.columns([3, 1, 1])
with col_a:
    st.write("**Anchor:** ", ANCHOR_DATE)
with col_b:
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()
with col_c:
    st.write("")

anchor_dt = datetime.fromisoformat(ANCHOR_DATE).replace(tzinfo=timezone.utc)
anchor_prices = fetch_anchor_prices()
current_prices = fetch_current_prices()

# ── Equity curves ────────────────────────────────────────────────────────────

st.subheader("Equity curves")

hodl_df = hodl_curve(anchor_prices, current_prices)
det_df = equity_curve_from_table("recommendations_deterministic", anchor_dt)
llm_df = equity_curve_from_table("recommendations", anchor_dt)

fig = go.Figure()
if not hodl_df.empty:
    fig.add_trace(go.Scatter(
        x=hodl_df["date"], y=hodl_df["equity"],
        name="HODL (1/3 BTC + 1/3 ETH + 1/3 RPL)", mode="lines",
        line=dict(color="#a3a3a3", width=2, dash="dot"),
    ))
if not det_df.empty:
    fig.add_trace(go.Scatter(
        x=det_df["date"], y=det_df["equity"],
        name="Deterministic (Strategy B)", mode="lines",
        line=dict(color="#10b981", width=2),
    ))
if not llm_df.empty:
    fig.add_trace(go.Scatter(
        x=llm_df["date"], y=llm_df["equity"],
        name="LLM Team (Strategy C)", mode="lines",
        line=dict(color="#60a5fa", width=2),
    ))

fig.add_hline(y=PORTFOLIO_SIZE, line_dash="dash", line_color="#525252",
              annotation_text="$124K starting capital")
fig.update_layout(
    height=420,
    template="plotly_dark",
    yaxis_title="Equity ($)",
    xaxis_title="",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)
st.plotly_chart(fig, use_container_width=True)


# ── Outperformance vs HODL summary ───────────────────────────────────────────

st.subheader("Outperformance vs HODL")

def latest_equity(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    return float(df.iloc[-1]["equity"])

hodl_now = latest_equity(hodl_df) or PORTFOLIO_SIZE
det_now = latest_equity(det_df)
llm_now = latest_equity(llm_df)

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("HODL", f"${hodl_now:,.0f}",
              f"{(hodl_now - PORTFOLIO_SIZE) / PORTFOLIO_SIZE * 100:+.2f}%")
with c2:
    if det_now is not None:
        gap_d = det_now - hodl_now
        st.metric("Deterministic", f"${det_now:,.0f}",
                  f"{(det_now - hodl_now) / hodl_now * 100:+.2f}% vs HODL")
    else:
        st.metric("Deterministic", EM_DASH, "no data yet")
with c3:
    if llm_now is not None:
        st.metric("LLM Team", f"${llm_now:,.0f}",
                  f"{(llm_now - hodl_now) / hodl_now * 100:+.2f}% vs HODL")
    else:
        st.metric("LLM Team", EM_DASH, "no data yet")


# ── Pre-mortem hypothesis dashboard ──────────────────────────────────────────

st.subheader("Pre-mortem hypothesis tests")
st.caption(
    "Each prediction the v2 reviewers made about how the plan will fail "
    "is encoded as a numerical test, run weekly. Green = predicted failure NOT "
    "happening. Red = failure mode confirmed."
)

results = latest_hypothesis_results()
if not results:
    st.info("No hypothesis tests have run yet. Run `python pre_mortem_tests.py` to populate.")
else:
    cols = st.columns(len(results))
    color_map = {"PASS": "#10b981", "CONFIRMED": "#ef4444",
                 "INSUFFICIENT_DATA": "#a3a3a3", "ERROR": "#f59e0b"}
    label_map = {
        "H1": "H1 — Regime paralysis (Gemini)",
        "H2": "H2 — Coarse classifier (Grok)",
        "H3": "H3 — Calibration on noise (ChatGPT)",
        "H4": "H4 — Tier 1 silently broken",
    }
    for i, r in enumerate(results):
        with cols[i]:
            color = color_map.get(r["status"], "#a3a3a3")
            st.markdown(
                f"""<div style="border-left: 4px solid {color}; padding: 8px 12px;
                            background: #18181b; border-radius: 4px;">
                <div style="color: {color}; font-weight: 600; font-size: 12px;">
                    {r['status']}
                </div>
                <div style="font-weight: 600; margin-top: 4px;">
                    {label_map.get(r['hypothesis'], r['hypothesis'])}
                </div>
                <div style="color: #a3a3a3; font-size: 12px; margin-top: 6px;">
                    {r['notes']}
                </div>
                <div style="color: #525252; font-size: 11px; margin-top: 6px;">
                    week {r['week_id']}
                </div>
                </div>""",
                unsafe_allow_html=True,
            )
            with st.expander("metrics"):
                try:
                    st.json(json.loads(r["metrics"] or "{}"))
                except Exception:
                    st.text(r.get("metrics") or "")


# ── Strategy box scores ──────────────────────────────────────────────────────

st.subheader("Strategy box scores (closed positions only)")

def box_score(table: str) -> Dict[str, Any]:
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not check:
            return {}
        r = conn.execute(
            f"SELECT COUNT(*) FILTER (WHERE status='CLOSED') AS closed, "
            f"COUNT(*) FILTER (WHERE status='EXPIRED') AS expired, "
            f"AVG(outcome_pct) FILTER (WHERE outcome_pct IS NOT NULL) AS avg_pct, "
            f"SUM(CASE WHEN outcome_pct > 0 THEN 1 ELSE 0 END) AS wins, "
            f"SUM(CASE WHEN outcome_pct <= 0 THEN 1 ELSE 0 END) AS losses, "
            f"SUM(outcome_pct * COALESCE(position_size_usd, 0) / 100.0) AS dollar_pnl "
            f"FROM {table}"
        ).fetchone()
        return {
            "closed": r[0] or 0,
            "expired": r[1] or 0,
            "avg_pct": r[2],
            "wins": r[3] or 0,
            "losses": r[4] or 0,
            "dollar_pnl": r[5] or 0.0,
        }

bs_llm = box_score("recommendations")
bs_det = box_score("recommendations_deterministic")

def fmt_score(s: Dict[str, Any]) -> Dict[str, Any]:
    if not s:
        return {}
    total = (s["wins"] + s["losses"])
    wr = s["wins"] / total if total else 0.0
    return {
        "Total trades": s["closed"] + s["expired"],
        "Closed (target/stop)": s["closed"],
        "Expired (48h)": s["expired"],
        "Wins": s["wins"],
        "Losses": s["losses"],
        "Win rate": f"{wr:.0%}" if total else EM_DASH,
        "Avg trade %": f"{s['avg_pct']:+.2f}%" if s.get("avg_pct") is not None else EM_DASH,
        "Realized $": f"${s['dollar_pnl']:+,.0f}",
    }

cc1, cc2 = st.columns(2)
with cc1:
    st.write("**Deterministic (Strategy B)**")
    box_b = fmt_score(bs_det)
    if box_b:
        st.dataframe(pd.DataFrame([box_b]).T.rename(columns={0: "value"}),
                     use_container_width=True)
    else:
        st.info("No deterministic strategy data yet — run `python run_deterministic_strategy.py`.")
with cc2:
    st.write("**LLM Team (Strategy C)**")
    box_c = fmt_score(bs_llm)
    if box_c:
        st.dataframe(pd.DataFrame([box_c]).T.rename(columns={0: "value"}),
                     use_container_width=True)
