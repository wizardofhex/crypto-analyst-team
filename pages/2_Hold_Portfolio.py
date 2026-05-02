"""
pages/2_Hold_Portfolio.py — Long-term hold position view.

Shows:
  - Current position value (10K RPL)
  - Latest HOLD/ADD/TRIM/EXIT consensus from the most recent monitor run
  - Per-analyst recommendation breakdown
  - History of past hold recommendations
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from config import DB_PATH, SYMBOL_TO_CG_ID

st.set_page_config(page_title="Hold Portfolio · Crypto Analyst Team", layout="wide")

EM_DASH = "—"


# ── Data helpers ─────────────────────────────────────────────────────────────


@st.cache_data(ttl=120)
def fetch_current_price(symbol: str) -> Optional[float]:
    cg_id = SYMBOL_TO_CG_ID.get(symbol)
    if not cg_id:
        return None
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            timeout=8,
        )
        if r.status_code == 200:
            return r.json().get(cg_id, {}).get("usd")
    except Exception:
        pass
    return None


def get_hold_positions() -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hold_positions'"
        ).fetchone()
        if not check:
            return []
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM hold_positions ORDER BY symbol").fetchall()
    return [dict(r) for r in rows]


def get_latest_hold_run(symbol: str) -> List[Dict[str, Any]]:
    """Fetch the most recent hold-recommendation set for a symbol."""
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hold_recommendations'"
        ).fetchone()
        if not check:
            return []
        conn.row_factory = sqlite3.Row
        latest_run = conn.execute(
            "SELECT run_id, MAX(timestamp) AS ts FROM hold_recommendations "
            "WHERE symbol = ? GROUP BY run_id ORDER BY ts DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not latest_run or not latest_run["run_id"]:
            return []
        rows = conn.execute(
            "SELECT * FROM hold_recommendations WHERE run_id = ? AND symbol = ? "
            "ORDER BY timestamp ASC",
            (latest_run["run_id"], symbol),
        ).fetchall()
    return [dict(r) for r in rows]


def get_hold_history(symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hold_recommendations'"
        ).fetchone()
        if not check:
            return []
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM hold_recommendations WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── UI ───────────────────────────────────────────────────────────────────────

st.title("Long-term Hold Portfolio")
st.caption(
    "Held positions outside the active trading universe. Monitored weekly "
    "via `run_hold_monitor.py` / `SKILL_rpl_hold.md`. Decision space is "
    "HOLD / ADD / TRIM / EXIT — not LONG/SHORT."
)

positions = get_hold_positions()
if not positions:
    st.warning(
        "No long-term hold positions recorded. Add one with "
        "`tracker.upsert_hold_position('RPL', 10000.0)`."
    )
    st.stop()

c_top1, c_top2 = st.columns([3, 1])
with c_top2:
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()


for pos in positions:
    sym = pos["symbol"]
    units = pos["units"]
    cost_basis = pos.get("cost_basis")

    st.divider()
    st.subheader(f"{sym} — {units:,.0f} units")
    if pos.get("notes"):
        st.caption(pos["notes"])

    current_price = fetch_current_price(sym)
    current_value = (units * current_price) if current_price else None

    cc1, cc2, cc3, cc4 = st.columns(4)
    with cc1:
        st.metric("Units", f"{units:,.0f}")
    with cc2:
        st.metric("Current price",
                  f"${current_price:,.4f}" if current_price else EM_DASH)
    with cc3:
        st.metric("Position value",
                  f"${current_value:,.0f}" if current_value else EM_DASH)
    with cc4:
        if cost_basis and current_price:
            pnl_pct = (current_price - cost_basis) / cost_basis * 100
            st.metric("Unrealized P&L",
                      f"{pnl_pct:+.1f}%",
                      f"vs basis ${cost_basis:.4f}")
        else:
            st.metric("Cost basis", "not set")

    # ── Latest run consensus ──────────────────────────────────────────────
    latest = get_latest_hold_run(sym)
    if not latest:
        st.info(
            f"No hold recommendations recorded for {sym}. Run "
            "`python run_hold_monitor.py` or trigger SKILL_rpl_hold.md in Cowork."
        )
        continue

    st.write("**Latest monitor run**")
    run_ts = latest[0].get("timestamp", EM_DASH)
    st.caption(f"Run timestamp: {run_ts}")

    # Mode consensus
    modes = [r["mode"] for r in latest if r.get("mode")]
    mode_counts = Counter(modes)
    consensus_mode, consensus_count = (mode_counts.most_common(1)[0]
                                          if mode_counts else (EM_DASH, 0))

    # Color the consensus
    color_map = {
        "HOLD": "#a3a3a3", "ADD": "#10b981",
        "TRIM": "#f59e0b", "EXIT": "#ef4444",
    }
    color = color_map.get(consensus_mode, "#a3a3a3")

    cm1, cm2 = st.columns([1, 3])
    with cm1:
        st.markdown(
            f"""<div style="background: #18181b; border-left: 6px solid {color};
                        padding: 12px 16px; border-radius: 4px;">
            <div style="color: #a3a3a3; font-size: 11px;">CONSENSUS</div>
            <div style="font-size: 28px; font-weight: 700; color: {color};">
                {consensus_mode}
            </div>
            <div style="color: #a3a3a3; font-size: 12px;">
                {consensus_count} of {len(latest)} analysts
            </div>
            </div>""",
            unsafe_allow_html=True,
        )
    with cm2:
        # Per-mode tally
        mode_table = pd.DataFrame(
            [{"mode": m, "count": c} for m, c in mode_counts.most_common()]
        )
        st.dataframe(mode_table, use_container_width=True, hide_index=True)

    # Per-analyst breakdown
    st.write("**Per-analyst recommendations**")
    rows_for_display = []
    for r in latest:
        rows_for_display.append({
            "analyst": r.get("analyst"),
            "mode": r.get("mode"),
            "urgency": r.get("urgency") or EM_DASH,
            "units": (f"{r['target_units']:,.0f}"
                       if r.get("target_units") else EM_DASH),
            "price": (f"${r['target_price']:.4f}"
                       if r.get("target_price") else EM_DASH),
            "confidence": r.get("confidence") or EM_DASH,
            "thesis": (r.get("thesis") or "")[:140],
        })
    st.dataframe(pd.DataFrame(rows_for_display),
                 use_container_width=True, hide_index=True)

    # ── History ────────────────────────────────────────────────────────────
    with st.expander(f"History — last 50 hold recs for {sym}"):
        hist = get_hold_history(sym, limit=50)
        if hist:
            hist_df = pd.DataFrame([
                {
                    "timestamp": h.get("timestamp", "")[:19],
                    "analyst": h.get("analyst"),
                    "mode": h.get("mode"),
                    "urgency": h.get("urgency") or EM_DASH,
                    "target_units": h.get("target_units"),
                    "target_price": h.get("target_price"),
                    "confidence": h.get("confidence"),
                    "current_price": h.get("current_price"),
                    "thesis": (h.get("thesis") or "")[:120],
                }
                for h in hist
            ])
            st.dataframe(hist_df, use_container_width=True, hide_index=True)
        else:
            st.write("No history.")
