"""
dashboard.py — Professional Streamlit trading analytics dashboard
for the Crypto Analyst Team system.

Launch:  streamlit run dashboard.py
"""

import io
import time
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from config import DB_PATH, ANALYST_ORDER, COINGECKO_BASE, SYMBOL_TO_CG_ID

# ─── Configuration ─────────────────────────────────────────────────────────────
ALT_ME_BASE = "https://api.alternative.me"
AUTO_REFRESH_SEC = 60
ANALYST_COLORS: Dict[str, str] = {
    "ARIA":   "#00d4ff",   # cyan
    "MARCUS": "#ffd700",   # gold
    "NOVA":   "#d966ff",   # violet
    "VEGA":   "#4a90ff",   # bright blue
    "DELTA":  "#00e5ff",   # bright cyan
    "CHAIN":  "#e0e0e0",   # bright white
    "QUANT":  "#ffeb3b",   # bright yellow
    "DEFI":   "#69f0ae",   # bright green
    "ATLAS":  "#ea80fc",   # bright magenta
    "REX":    "#00ff88",   # neon green
    "ZEN":    "#ff4757",   # neon red
}

# Use the canonical symbol map from config (avoids duplication / drift)
CG_ID = SYMBOL_TO_CG_ID

# ─── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Crypto Analyst Team",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Global CSS — dark trading terminal aesthetic ─────────────────────────────
st.markdown("""
<style>
/* ── Variables ── */
:root {
    --bg:         #0d1117;
    --card:       #161b22;
    --card2:      #1c2333;
    --border:     #30363d;
    --text:       #e6edf3;
    --muted:      #8b949e;
    --dim:        #484f58;
    --green:      #00ff88;
    --red:        #ff4757;
    --yellow:     #ffd700;
    --cyan:       #00d4ff;
    --violet:     #d966ff;
    --blue:       #58a6ff;
}

/* App background */
.stApp, .stApp > header        { background-color: var(--bg) !important; }
.main .block-container          { padding: 1.25rem 2rem 3rem; max-width: 1420px; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #090d14 !important;
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] * { color: var(--text) !important; }

/* KPI cards */
.kpi {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.1rem 1.3rem;
    text-align: center;
    position: relative;
    overflow: hidden;
    height: 110px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.kpi::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--cyan), var(--green));
}
.kpi-label {
    font-size: 0.65rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.35rem;
}
.kpi-val {
    font-size: 1.9rem;
    font-weight: 700;
    font-family: 'Courier New', monospace;
    line-height: 1.1;
    color: var(--text);
}
.kpi-val.pos  { color: var(--green); }
.kpi-val.neg  { color: var(--red);   }
.kpi-val.info { color: var(--cyan);  }
.kpi-sub {
    font-size: 0.68rem;
    color: var(--dim);
    margin-top: 0.3rem;
}

/* Section headers */
.sec-hdr {
    font-size: 0.62rem;
    font-weight: 700;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.15em;
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin: 1.4rem 0 0.8rem;
}

/* Status dot */
.dot {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
    margin-right: 5px;
    animation: blink 2.2s ease-in-out infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }

/* Streamlit overrides */
div[data-testid="stMetric"]      { background: var(--card); border: 1px solid var(--border);
                                    border-radius: 8px; padding: .8rem 1rem; }
div[data-testid="stExpander"]    { border: 1px solid var(--border); border-radius: 6px; }

/* ── Dataframe / Table — full dark theme ── */
div[data-testid="stDataFrame"]   { border: 1px solid var(--border); border-radius: 6px;
                                   overflow: hidden; }
/* Glide data grid (Streamlit's table renderer) */
div[data-testid="stDataFrame"] [data-testid="glideDataEditor"],
div[data-testid="stDataFrame"] canvas { background: var(--card) !important; }
.stDataFrame thead tr th         { background: var(--card2) !important; font-size: .72rem !important;
                                   text-transform: uppercase; letter-spacing: .05em;
                                   color: var(--muted) !important; }
.stDataFrame tbody tr td         { background: var(--card) !important;
                                   color: var(--text) !important;
                                   border-color: var(--border) !important; }
.stDataFrame tbody tr:nth-child(even) td { background: var(--card2) !important; }
/* Arrow table fallback */
div[data-testid="stTable"] table { background: var(--card) !important;
                                   color: var(--text) !important; }
div[data-testid="stTable"] th    { background: var(--card2) !important;
                                   color: var(--muted) !important;
                                   border-color: var(--border) !important; }
div[data-testid="stTable"] td    { background: var(--card) !important;
                                   color: var(--text) !important;
                                   border-color: var(--border) !important; }
/* Pandas styler / st.dataframe inner iframe */
.stDataFrame iframe              { background: var(--card) !important; }
/* Generic table elements inside markdown */
.stApp table                     { background: var(--card) !important; color: var(--text) !important; }
.stApp table th                  { background: var(--card2) !important; color: var(--muted) !important;
                                   border-color: var(--border) !important; }
.stApp table td                  { border-color: var(--border) !important; }

/* Scrollbar */
::-webkit-scrollbar              { width: 5px; height: 5px; }
::-webkit-scrollbar-track        { background: var(--bg); }
::-webkit-scrollbar-thumb        { background: var(--border); border-radius: 3px; }

/* ── Top toolbar / header bar ── */
header[data-testid="stHeader"]   { background: var(--bg) !important;
                                   border-bottom: 1px solid var(--border) !important; }
div[data-testid="stToolbar"]     { background: transparent !important; }
div[data-testid="stDecoration"]  { background: transparent !important; display: none !important; }
div[data-testid="stStatusWidget"]{ background: var(--card) !important;
                                   color: var(--text) !important; }

/* ── Radio buttons — style as nav items, hide only the circle ── */
div[data-testid="stRadio"] > div[role="radiogroup"] { gap: 2px !important; }
div[data-testid="stRadio"] label {
    font-size: 0.82rem !important;
    color: var(--muted) !important;
    padding: 0.45rem 0.7rem !important;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s;
}
div[data-testid="stRadio"] label:hover {
    color: var(--text) !important;
    background: var(--card) !important;
}
/* Selected state — cyan accent */
div[data-testid="stRadio"] label[data-checked="true"],
div[data-testid="stRadio"] label[aria-checked="true"] {
    color: var(--cyan) !important;
    background: var(--card2) !important;
    font-weight: 600;
    border-left: 2px solid var(--cyan);
}
/* Make sure label text (p tags inside) inherits color */
div[data-testid="stRadio"] label p {
    color: inherit !important;
    margin: 0 !important;
}
/* Hide ONLY the radio circle dot — target the small round indicator div */
div[data-testid="stRadio"] label > div[data-testid="stThumbValue"],
div[data-testid="stRadio"] [role="radio"]::before,
[data-baseweb="radio"] > div > div:first-child > div:first-child {
    display: none !important;
}
/* Baseweb radio: hide the circle but keep the label */
[data-baseweb="radio"] > div { border: none !important;
                                background: transparent !important; }
[data-baseweb="radio"] label { color: var(--text) !important; }

/* ── Buttons (refresh, download, etc.) ── */
.stButton button, .stDownloadButton button {
    background: var(--card2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 6px; font-size: 0.8rem;
    transition: border-color 0.2s, background 0.2s;
}
.stButton button:hover, .stDownloadButton button:hover {
    border-color: var(--cyan) !important;
    background: var(--card) !important;
    color: #ffffff !important;
}
.stButton button:active {
    background: var(--border) !important;
}

/* ── Select boxes / dropdowns ── */
div[data-baseweb="select"] > div { background: var(--card) !important;
                                   border-color: var(--border) !important;
                                   color: var(--text) !important; }
div[data-baseweb="select"] span  { color: var(--text) !important; }
[data-baseweb="popover"] ul      { background: var(--card) !important;
                                   border: 1px solid var(--border) !important; }
[data-baseweb="popover"] li      { color: var(--text) !important; }
[data-baseweb="popover"] li:hover{ background: var(--card2) !important; }

/* ── Multiselect / tags ── */
[data-baseweb="tag"]             { background: var(--card2) !important;
                                   border-color: var(--border) !important;
                                   color: var(--text) !important; }

/* ── Checkbox ── */
div[data-testid="stCheckbox"] label span { color: var(--text) !important; }

/* ── Dividers ── */
hr                               { border-color: var(--border) !important; }

/* ── Tab bar ── */
button[data-baseweb="tab"]       { color: var(--muted) !important;
                                   background: transparent !important; }
button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--cyan) !important;
    border-bottom-color: var(--cyan) !important;
}

/* ── Plotly modebar (chart toolbar) ── */
.modebar                         { background: transparent !important; }
.modebar-btn path                { fill: var(--muted) !important; }
.modebar-btn:hover path          { fill: var(--cyan) !important; }

/* ── All remaining text elements ── */
.stApp p, .stApp span, .stApp div, .stApp label {
    color: var(--text); }
.stApp .stMarkdown p             { color: var(--text); }

/* ── Spinner ── */
div[data-testid="stSpinner"] span { color: var(--muted) !important; }
</style>
""", unsafe_allow_html=True)

# ─── Plotly base layout (applied to every chart) ──────────────────────────────
_PL = dict(
    template="plotly_dark",
    paper_bgcolor="#161b22",
    plot_bgcolor="#161b22",
    font=dict(color="#e6edf3", family="'Courier New', monospace", size=11),
    margin=dict(l=45, r=15, t=35, b=40),
    xaxis=dict(gridcolor="#30363d", zerolinecolor="#30363d"),
    yaxis=dict(gridcolor="#30363d", zerolinecolor="#30363d"),
    legend=dict(bgcolor="#161b22", bordercolor="#30363d", font=dict(size=10)),
)


def ply(**overrides):
    """Merge overrides into the base Plotly layout dict."""
    out = dict(_PL)
    out.update(overrides)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def _db() -> sqlite3.Connection:
    """Return a new per-call SQLite connection (thread-safe by isolation)."""
    if not DB_PATH.exists():
        st.error(
            f"**Database not found:** `{DB_PATH}`\n\n"
            "Run `python main.py` first to initialise the database."
        )
        st.stop()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def qdf(sql: str, params=()) -> pd.DataFrame:
    """Execute a SQL SELECT and return a pandas DataFrame."""
    try:
        return pd.read_sql_query(sql, _db(), params=params)
    except Exception as exc:
        st.warning(f"DB query failed: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_recs(status: str = "") -> pd.DataFrame:
    if status:
        sql = "SELECT * FROM recommendations WHERE status = ? ORDER BY timestamp DESC"
        df = qdf(sql, params=(status,))
    else:
        df = qdf("SELECT * FROM recommendations ORDER BY timestamp DESC")
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=30)
def load_stats() -> pd.DataFrame:
    return qdf("SELECT * FROM analyst_stats ORDER BY analyst")


@st.cache_data(ttl=30)
def load_lookbacks() -> pd.DataFrame:
    df = qdf("SELECT symbol, days, generated_at, summary FROM lookback_memory ORDER BY generated_at DESC")
    if not df.empty and "generated_at" in df.columns:
        df["generated_at"] = pd.to_datetime(df["generated_at"], utc=True, errors="coerce")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# EXTERNAL DATA
# ═══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: dict = None, timeout: int = 10) -> Optional[Any]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_fg() -> Dict:
    data = _get(f"{ALT_ME_BASE}/fng/", {"limit": 30})
    if not data or "data" not in data:
        return {"current": 50, "label": "Neutral", "history": []}
    entries = data["data"]
    return {
        "current": int(entries[0]["value"]),
        "label": entries[0].get("value_classification", "Neutral"),
        "history": [{"ts": int(e["timestamp"]), "val": int(e["value"])} for e in entries],
    }


@st.cache_data(ttl=60)
def fetch_prices(symbols: tuple) -> Dict[str, float]:
    """Batch fetch current USD prices from CoinGecko."""
    if not symbols:
        return {}
    ids = ",".join(CG_ID.get(s.upper(), s.lower()) for s in symbols)
    data = _get(f"{COINGECKO_BASE}/simple/price", {"ids": ids, "vs_currencies": "usd"})
    if not data:
        return {}
    result: Dict[str, float] = {}
    for sym in symbols:
        cg_id = CG_ID.get(sym.upper(), sym.lower())
        price = (data.get(cg_id) or {}).get("usd")
        if price is not None:
            result[sym.upper()] = float(price)
    return result


@st.cache_data(ttl=300)
def fetch_sparkline(symbol: str, days: int = 7) -> List[float]:
    cg_id = CG_ID.get(symbol.upper(), symbol.lower())
    data = _get(
        f"{COINGECKO_BASE}/coins/{cg_id}/market_chart",
        {"vs_currency": "usd", "days": days, "interval": "hourly"},
    )
    if not data:
        return []
    return [p[1] for p in data.get("prices", [])]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def fp(v: Optional[float]) -> str:
    """Format a price value."""
    if v is None:
        return "—"
    if v < 0.001:
        return f"${v:.6f}"
    if v < 1:
        return f"${v:.4f}"
    return f"${v:,.2f}"


def fpc(v: Optional[float], sign: bool = True) -> str:
    """Format a percentage value."""
    if v is None:
        return "—"
    s = "+" if v > 0 and sign else ""
    return f"{s}{v:.2f}%"


def kpi(label: str, value: str, sub: str = "", cls: str = "") -> None:
    """Render an HTML KPI card."""
    st.markdown(
        f'<div class="kpi">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-val {cls}">{value}</div>'
        f'{"<div class=kpi-sub>" + sub + "</div>" if sub else ""}'
        f"</div>",
        unsafe_allow_html=True,
    )


def sec(title: str) -> None:
    """Render a section header."""
    st.markdown(f'<div class="sec-hdr">{title}</div>', unsafe_allow_html=True)


def unrealized_pnl(rec: pd.Series, current: float) -> Optional[float]:
    entry = rec.get("entry_price")
    if not entry or entry == 0 or current is None:
        return None
    direction = str(rec.get("recommendation", "LONG"))
    raw = (current - entry) / entry * 100
    return round(-raw if direction == "SHORT" else raw, 2)


def fmt_pnl_cell_color(col: pd.Series) -> List[str]:
    """Return per-cell CSS text-color styles for a P&L string column (green=positive, red=negative)."""
    styles = []
    for v in col:
        s = str(v)
        if s.startswith("+"):    styles.append("color:#00ff88")
        elif s.startswith("-"):  styles.append("color:#ff4757")
        else:                    styles.append("")
    return styles


def sharpe_ratio(returns: List[float]) -> float:
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    sd = arr.std()
    return round(float(arr.mean() / sd), 2) if sd else 0.0


def held_for(ts) -> str:
    if ts is None:
        return "—"
    try:
        now = datetime.now(timezone.utc)
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        secs = (now - ts).total_seconds()
        if secs < 3600:
            return f"{int(secs // 60)}m"
        if secs < 86400:
            return f"{int(secs // 3600)}h"
        return f"{int(secs // 86400)}d"
    except Exception:
        return "—"


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR + AUTO-REFRESH
# ═══════════════════════════════════════════════════════════════════════════════

def sidebar() -> str:
    with st.sidebar:
        st.markdown(
            "<div style='text-align:center;padding:1rem 0 .5rem'>"
            "<div style='font-size:2rem'>📈</div>"
            "<div style='font-size:.95rem;font-weight:700;color:#e6edf3;letter-spacing:.05em'>"
            "ANALYST TEAM</div>"
            "<div style='font-size:.6rem;color:#8b949e;letter-spacing:.12em;margin-top:3px'>"
            "CRYPTO INTELLIGENCE TERMINAL</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        page = st.radio(
            "nav",
            [
                "📊  Overview",
                "🏆  Leaderboard",
                "🔴  Active Positions",
                "📈  Performance",
                "📋  History",
                "🪙  Coin Analysis",
                "🧠  Lookback Insights",
            ],
            label_visibility="collapsed",
        )

        st.divider()

        # Timer
        if "last_refresh" not in st.session_state:
            st.session_state["last_refresh"] = time.time()
        elapsed = time.time() - st.session_state["last_refresh"]
        remaining = max(0, AUTO_REFRESH_SEC - elapsed)

        st.markdown(
            f"<div style='font-size:.68rem;color:#8b949e;text-align:center'>"
            f"<span class='dot'></span>LIVE &nbsp;·&nbsp; refresh in {int(remaining)}s"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("⟳  Refresh now", use_container_width=True):
            st.cache_data.clear()
            st.session_state["last_refresh"] = time.time()
            st.rerun()

        if elapsed >= AUTO_REFRESH_SEC:
            st.cache_data.clear()
            st.session_state["last_refresh"] = time.time()
            st.rerun()

        st.markdown(
            f"<div style='font-size:.6rem;color:#484f58;text-align:center;margin-top:.5rem'>"
            f"Updated {datetime.now().strftime('%H:%M:%S')}</div>",
            unsafe_allow_html=True,
        )

    return page.split("  ", 1)[-1].strip()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

def page_overview():
    st.markdown("### 📊 Overview")

    all_recs  = load_recs()
    closed    = all_recs[all_recs["status"] == "CLOSED"] if not all_recs.empty else pd.DataFrame()
    open_recs = all_recs[all_recs["status"] == "OPEN"]   if not all_recs.empty else pd.DataFrame()

    total_closed = len(closed)
    wins         = int((closed["outcome_pct"] > 0).sum()) if not closed.empty else 0
    win_rate     = round(wins / total_closed * 100, 1) if total_closed else 0.0
    total_pnl    = float(closed["outcome_pct"].sum()) if not closed.empty else 0.0
    open_count   = len(open_recs)
    avg_conf     = round(float(all_recs["confidence"].mean()), 1) if not all_recs.empty and "confidence" in all_recs else 0.0

    # ── Dollar P&L metrics ────────────────────────────────────────────────
    realized_pnl_usd = 0.0
    if not closed.empty and "position_size_usd" in closed.columns and "outcome_pct" in closed.columns:
        _mask = closed["position_size_usd"].notna() & closed["outcome_pct"].notna()
        realized_pnl_usd = float(
            (closed.loc[_mask, "outcome_pct"] / 100 * closed.loc[_mask, "position_size_usd"]).sum()
        )

    deployed_capital = 0.0
    if not open_recs.empty and "position_size_usd" in open_recs.columns:
        deployed_capital = float(open_recs["position_size_usd"].dropna().sum())

    # ── KPI Row ───────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi("Team Win Rate",    f"{win_rate}%",       f"{total_closed} closed calls",   "pos" if win_rate >= 50 else "neg")
    with c2: kpi("Total Calls",      str(len(all_recs)),   f"{open_count} open · {total_closed} closed", "info")
    with c3: kpi("Closed P&L",       fpc(total_pnl),       "sum of all outcomes",             "pos" if total_pnl >= 0 else "neg")
    with c4: kpi("Open Positions",   str(open_count),      "tracked recommendations",         "info")
    with c5: kpi("Avg Confidence",   f"{avg_conf}/10",     "across all calls",                "info")

    # ── Dollar KPI Row ────────────────────────────────────────────────────
    if realized_pnl_usd > 0:
        _rpnl_str = f"+${realized_pnl_usd:,.0f}"
    elif realized_pnl_usd < 0:
        _rpnl_str = f"-${abs(realized_pnl_usd):,.0f}"
    else:
        _rpnl_str = "$0"
    _dep_str = f"${deployed_capital:,.0f}" if deployed_capital > 0 else "—"
    d1, d2 = st.columns(2)
    with d1: kpi("Total Realized P&L $", _rpnl_str, "closed positions w/ size data",  "pos" if realized_pnl_usd >= 0 else "neg")
    with d2: kpi("Total Deployed Capital", _dep_str, "sum of open position sizes", "info")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Fear & Greed | Recent calls ────────────────────────────────────────
    col_fg, col_right = st.columns([1, 2])

    with col_fg:
        sec("Fear & Greed Index")
        fg = fetch_fg()
        v  = fg["current"]

        # Gauge colour zones
        if   v < 25: gc = "#ff4757"
        elif v < 45: gc = "#ff7f50"
        elif v < 55: gc = "#ffd700"
        elif v < 75: gc = "#7fff00"
        else:        gc = "#00ff88"

        fig_g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=v,
            title={"text": fg["label"], "font": {"size": 13, "color": gc}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#8b949e", "tickfont": {"size": 9}},
                "bar":  {"color": gc, "thickness": 0.28},
                "bgcolor": "#161b22",
                "borderwidth": 0,
                "steps": [
                    {"range": [0,  25], "color": "rgba(255,71,87,.18)"},
                    {"range": [25, 45], "color": "rgba(255,127,80,.15)"},
                    {"range": [45, 55], "color": "rgba(255,215,0,.12)"},
                    {"range": [55, 75], "color": "rgba(127,255,0,.13)"},
                    {"range": [75,100], "color": "rgba(0,255,136,.18)"},
                ],
                "threshold": {"line": {"color": gc, "width": 3},
                              "thickness": 0.72, "value": v},
            },
            number={"font": {"size": 34, "color": gc, "family": "Courier New"}},
        ))
        fig_g.update_layout(height=215, paper_bgcolor="#161b22",
                            font=dict(color="#8b949e"), margin=dict(l=15,r=15,t=30,b=5))
        st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})

        # 30-day history trend
        if fg["history"]:
            hdf = pd.DataFrame(fg["history"])
            hdf["ts"] = pd.to_datetime(hdf["ts"], unit="s")
            fig_t = go.Figure(go.Scatter(
                x=hdf["ts"], y=hdf["val"],
                fill="tozeroy", fillcolor="rgba(0,212,255,.07)",
                line=dict(color="#00d4ff", width=1.5), mode="lines",
            ))
            fig_t.update_layout(height=90, paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                                margin=dict(l=0,r=0,t=0,b=0),
                                xaxis=dict(visible=False), yaxis=dict(range=[0,100],visible=False),
                                showlegend=False)
            st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})

    with col_right:
        sec("Recent Calls")
        if all_recs.empty:
            st.info("No recommendations yet — start the analyst chat to generate calls.")
        else:
            disp = all_recs.head(10)[["timestamp","analyst","symbol","recommendation","confidence","status","outcome_pct"]].copy()
            disp["timestamp"] = disp["timestamp"].dt.strftime("%m-%d %H:%M")
            disp["outcome_pct"] = disp["outcome_pct"].apply(lambda x: fpc(x) if x is not None else "OPEN")
            disp.columns = ["Time","Analyst","Coin","Direction","Conf","Status","P&L"]
            st.dataframe(disp, use_container_width=True, hide_index=True, height=320)

        # Call counts bar
        if not all_recs.empty:
            sec("Calls by Analyst")
            counts = all_recs["analyst"].value_counts().reindex(ANALYST_ORDER, fill_value=0)
            fig_b = go.Figure(go.Bar(
                x=counts.index,
                y=counts.values,
                marker_color=[ANALYST_COLORS.get(a, "#58a6ff") for a in counts.index],
                text=counts.values, textposition="outside",
            ))
            fig_b.update_layout(**ply(height=170, showlegend=False,
                                      yaxis=dict(visible=False,**_PL["yaxis"]),
                                      margin=dict(l=0,r=0,t=10,b=0)))
            st.plotly_chart(fig_b, use_container_width=True, config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — LEADERBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def page_leaderboard():
    st.markdown("### 🏆 Analyst Leaderboard")

    all_recs = load_recs()
    stats_df = load_stats()
    if all_recs.empty:
        st.info("No data yet.")
        return

    # ── Build enriched leaderboard ─────────────────────────────────────────
    rows = []
    for analyst in ANALYST_ORDER:
        sub    = all_recs[all_recs["analyst"] == analyst]
        closed = sub[sub["status"] == "CLOSED"]
        outcomes = closed["outcome_pct"].dropna().tolist()

        # ── Dollar P&L for this analyst ───────────────────────────────────
        _pnl_usd_parts: List[float] = []
        if not closed.empty and "position_size_usd" in closed.columns:
            for _, _cr in closed.iterrows():
                _pct = _cr.get("outcome_pct")
                _usd = _cr.get("position_size_usd")
                if pd.notna(_pct) and pd.notna(_usd):
                    _pnl_usd_parts.append(float(_pct) / 100 * float(_usd))
        _analyst_pnl_usd = sum(_pnl_usd_parts) if _pnl_usd_parts else None

        s    = stats_df[stats_df["analyst"] == analyst]
        total = int(s["total_calls"].iloc[0]) if not s.empty else 0
        wins  = int(s["wins"].iloc[0])         if not s.empty else 0

        if _analyst_pnl_usd is not None:
            _pnl_usd_fmt = f"+${_analyst_pnl_usd:,.0f}" if _analyst_pnl_usd >= 0 else f"-${abs(_analyst_pnl_usd):,.0f}"
        else:
            _pnl_usd_fmt = "—"

        rows.append({
            "Analyst":       analyst,
            "Calls":         len(sub),
            "Closed":        total,
            "Win Rate %":    round(wins / total * 100, 1) if total else 0.0,
            "Avg Return %":  round(np.mean(outcomes), 2)  if outcomes else 0.0,
            "Best %":        round(max(outcomes), 2)       if outcomes else 0.0,
            "Worst %":       round(min(outcomes), 2)       if outcomes else 0.0,
            "Avg Conf":      round(float(sub["confidence"].mean()), 1) if not sub.empty else 0.0,
            "Sharpe":        sharpe_ratio(outcomes),
            "Total P&L $":   _pnl_usd_fmt,
        })

    lb = pd.DataFrame(rows)

    # Sort control
    sort_col = st.selectbox(
        "Sort by",
        ["Win Rate %", "Avg Return %", "Sharpe", "Best %", "Calls"],
        key="lb_sort",
    )
    lb = lb.sort_values(sort_col, ascending=False).reset_index(drop=True)
    lb.insert(0, "Rank", range(1, len(lb) + 1))

    sec("Rankings")
    styled = (
        lb.style
        .background_gradient(subset=["Win Rate %"],   cmap="RdYlGn", vmin=0,   vmax=100)
        .background_gradient(subset=["Avg Return %"], cmap="RdYlGn", vmin=-20, vmax=20)
        .format({
            "Win Rate %":   "{:.1f}%",
            "Avg Return %": lambda x: fpc(x),
            "Best %":       lambda x: fpc(x),
            "Worst %":      lambda x: fpc(x),
            "Sharpe":       "{:.2f}",
            "Avg Conf":     "{:.1f}",
        })
        .apply(fmt_pnl_cell_color, subset=["Total P&L $"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True, height=240)

    # ── Charts row ─────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        sec("Win Rate %")
        fig = go.Figure(go.Bar(
            x=lb["Analyst"], y=lb["Win Rate %"],
            marker=dict(color=lb["Win Rate %"],
                        colorscale=[[0,"#ff4757"],[.5,"#ffd700"],[1,"#00ff88"]],
                        cmin=0, cmax=100, showscale=False),
            text=[f"{v:.1f}%" for v in lb["Win Rate %"]], textposition="outside",
        ))
        fig.add_hline(y=50, line_dash="dash", line_color="#484f58", line_width=1)
        fig.update_layout(**ply(height=270, showlegend=False,
                                yaxis=dict(range=[0,115],**_PL["yaxis"])))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with c2:
        sec("Avg Return %")
        fig2 = go.Figure(go.Bar(
            x=lb["Analyst"], y=lb["Avg Return %"],
            marker_color=["#00ff88" if v >= 0 else "#ff4757" for v in lb["Avg Return %"]],
            text=[fpc(v) for v in lb["Avg Return %"]], textposition="outside",
        ))
        fig2.add_hline(y=0, line_color="#30363d", line_width=1)
        fig2.update_layout(**ply(height=270, showlegend=False))
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    # ── Radar chart ────────────────────────────────────────────────────────
    sec("Multi-Metric Spider")
    metrics = ["Win Rate %", "Avg Return %", "Best %", "Avg Conf", "Sharpe"]
    fig_r = go.Figure()

    for _, row in lb.iterrows():
        analyst = row["Analyst"]
        vals = []
        for m in metrics:
            col_vals = lb[m]
            mn, mx = col_vals.min(), col_vals.max()
            norm = (row[m] - mn) / (mx - mn) if mx != mn else 0.5
            vals.append(round(norm * 100, 1))
        vals.append(vals[0])

        hex_c = ANALYST_COLORS.get(analyst, "#58a6ff").lstrip("#")
        rgba  = tuple(int(hex_c[i:i+2], 16) for i in (0, 2, 4))
        fig_r.add_trace(go.Scatterpolar(
            r=vals, theta=metrics + [metrics[0]],
            fill="toself",
            fillcolor=f"rgba({rgba[0]},{rgba[1]},{rgba[2]},0.14)",
            line=dict(color=ANALYST_COLORS.get(analyst, "#58a6ff"), width=2),
            name=analyst,
        ))

    fig_r.update_layout(
        polar=dict(
            bgcolor="#161b22",
            radialaxis=dict(visible=True, range=[0,100], gridcolor="#30363d", tickfont=dict(size=8)),
            angularaxis=dict(gridcolor="#30363d"),
        ),
        paper_bgcolor="#161b22", font=dict(color="#e6edf3"),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d"),
        height=380, margin=dict(l=60,r=60,t=20,b=20),
    )
    st.plotly_chart(fig_r, use_container_width=True, config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — ACTIVE POSITIONS
# ═══════════════════════════════════════════════════════════════════════════════

def page_active():
    st.markdown("### 🔴 Active Positions")

    open_recs = load_recs("OPEN")
    if open_recs.empty:
        st.info("No open recommendations. Use the analyst chat to generate calls.")
        return

    syms   = tuple(open_recs["symbol"].unique().tolist())
    prices = fetch_prices(syms)

    # ── Enrich rows ────────────────────────────────────────────────────────
    rows = []
    for _, rec in open_recs.iterrows():
        sym     = rec["symbol"]
        cur     = prices.get(sym)
        entry   = rec.get("entry_price")
        unreal  = unrealized_pnl(rec, cur) if cur else None
        target  = rec.get("target_price")
        stop    = rec.get("stop_loss")
        direction = str(rec.get("recommendation","LONG"))

        # ── Position size display ─────────────────────────────────────────
        pos_usd     = rec.get("position_size_usd")
        pos_pct_val = rec.get("position_size_pct")
        _pusd_ok    = pd.notna(pos_usd)
        _ppct_ok    = pd.notna(pos_pct_val)
        if _pusd_ok:
            pos_size_str = f"${float(pos_usd):,.0f}"
            if _ppct_ok:
                pos_size_str += f" ({float(pos_pct_val):.1f}%)"
        else:
            pos_size_str = "—"

        # ── Unrealized P&L $ (uses already-fetched current price) ─────────
        if cur and entry and entry > 0 and _pusd_ok:
            _pnl_usd = ((cur - entry) / entry if direction == "LONG" else (entry - cur) / entry) * float(pos_usd)
            pnl_usd_str = f"+${_pnl_usd:,.0f}" if _pnl_usd >= 0 else f"-${abs(_pnl_usd):,.0f}"
        else:
            pnl_usd_str = "—"

        pct_tgt = None
        pct_stp = None
        if cur and target:
            raw = (target - cur) / cur * 100
            pct_tgt = raw if direction == "LONG" else -raw
        if cur and stop:
            raw = (stop - cur) / cur * 100
            pct_stp = raw if direction == "LONG" else -raw

        rows.append({
            "Coin":      sym,
            "Analyst":   rec["analyst"],
            "Dir":       direction,
            "Pos Size":  pos_size_str,
            "Entry":     fp(entry),
            "Current":   fp(cur) if cur else "—",
            "Unreal %":  fpc(unreal) if unreal is not None else "—",
            "Unreal $":  pnl_usd_str,
            "Target":    fp(target),
            "Stop":      fp(stop),
            "Conf":      f"{int(rec['confidence'])}/10" if rec.get("confidence") else "—",
            "Open":      held_for(rec.get("timestamp")),
            "→ Target":  fpc(pct_tgt) if pct_tgt is not None else "—",
            "→ Stop":    fpc(pct_stp) if pct_stp is not None else "—",
            "_raw_pnl":  unreal,
        })

    df = pd.DataFrame(rows)
    profitable = sum(1 for r in rows if r["_raw_pnl"] and r["_raw_pnl"] > 0)
    longs  = sum(1 for r in rows if r["Dir"] == "LONG")
    shorts = sum(1 for r in rows if r["Dir"] == "SHORT")
    avg_u  = float(np.mean([r["_raw_pnl"] for r in rows if r["_raw_pnl"] is not None] or [0]))

    # ── KPI strip ──────────────────────────────────────────────────────────
    c1,c2,c3 = st.columns(3)
    with c1: kpi("Open Positions",       str(len(df)),      f"{longs} LONG · {shorts} SHORT", "info")
    with c2: kpi("Currently Profitable", str(profitable),   f"{len(df)-profitable} at a loss", "pos" if profitable >= len(df)//2 else "neg")
    with c3: kpi("Avg Unrealized P&L",   fpc(avg_u),        "all open positions", "pos" if avg_u >= 0 else "neg")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Table with row colouring ───────────────────────────────────────────
    sec("Open Positions")
    display = df.drop(columns=["_raw_pnl"])

    def _row_color(row):
        try:
            val = float(row["Unreal %"].replace("%","").replace("+",""))
        except Exception:
            val = 0
        if   val >  5: bg = "background-color:rgba(0,255,136,.13)"
        elif val >  0: bg = "background-color:rgba(0,255,136,.06)"
        elif val < -5: bg = "background-color:rgba(255,71,87,.13)"
        elif val <  0: bg = "background-color:rgba(255,71,87,.06)"
        else:          bg = ""
        return [bg] * len(row)

    st.dataframe(
        display.style
            .apply(_row_color, axis=1)
            .apply(fmt_pnl_cell_color, subset=["Unreal %", "Unreal $"]),
        use_container_width=True,
        hide_index=True,
        height=max(180, 38 * len(display) + 42),
    )
    st.caption("⚡ Unrealized P&L $ is estimated from last fetched price — click 'Refresh now' to update.")

    # ── P&L bar ────────────────────────────────────────────────────────────
    pnl_rows = [(f"{r['Coin']}\n{r['Analyst']}", r["_raw_pnl"]) for r in rows if r["_raw_pnl"] is not None]
    if pnl_rows and prices:
        sec("Unrealized P&L by Position")
        lbls, vals = zip(*pnl_rows)
        fig = go.Figure(go.Bar(
            x=list(lbls), y=list(vals),
            marker_color=["#00ff88" if v >= 0 else "#ff4757" for v in vals],
            text=[fpc(v) for v in vals], textposition="outside",
        ))
        fig.add_hline(y=0, line_color="#8b949e", line_width=1)
        fig.update_layout(**ply(height=260, showlegend=False,
                                xaxis=dict(tickfont=dict(size=9),**_PL["xaxis"])))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — PERFORMANCE OVER TIME
# ═══════════════════════════════════════════════════════════════════════════════

def page_performance():
    st.markdown("### 📈 Performance Over Time")

    all_recs = load_recs()
    if all_recs.empty:
        st.info("No data yet.")
        return

    closed = all_recs[all_recs["status"] == "CLOSED"].copy()

    # Analyst filter
    analysts_sel = st.multiselect("Analysts", ANALYST_ORDER, default=ANALYST_ORDER, key="perf_sel")

    # ── Cumulative win rate ────────────────────────────────────────────────
    sec("Cumulative Win Rate Over Time")
    fig_wr = go.Figure()
    for analyst in analysts_sel:
        sub = closed[closed["analyst"] == analyst].sort_values("timestamp")
        if sub.empty:
            continue
        wins_cum  = (sub["outcome_pct"] > 0).cumsum()
        total_cum = pd.Series(range(1, len(sub) + 1), index=sub.index)
        fig_wr.add_trace(go.Scatter(
            x=sub["timestamp"], y=(wins_cum / total_cum * 100),
            mode="lines", name=analyst,
            line=dict(color=ANALYST_COLORS.get(analyst,"#58a6ff"), width=2),
        ))
    fig_wr.add_hline(y=50, line_dash="dash", line_color="#484f58", line_width=1)
    fig_wr.update_layout(**ply(height=300, yaxis=dict(range=[0,105], title="Win Rate %",**_PL["yaxis"])))
    st.plotly_chart(fig_wr, use_container_width=True, config={"displayModeBar": False})

    # ── Monthly volume | Confidence scatter ────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        sec("Monthly Call Volume by Analyst")
        monthly = all_recs.copy()
        monthly["month"] = monthly["timestamp"].dt.strftime("%Y-%m")
        mc = monthly.groupby(["month","analyst"]).size().reset_index(name="n")
        fig_m = px.bar(mc, x="month", y="n", color="analyst",
                       color_discrete_map=ANALYST_COLORS, barmode="stack")
        fig_m.update_layout(**ply(height=290))
        st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})

    with c2:
        sec("Confidence Score vs Actual Return")
        if not closed.empty and "confidence" in closed.columns:
            scat = closed.dropna(subset=["confidence","outcome_pct"])
            if not scat.empty:
                # Trend line
                z = np.polyfit(scat["confidence"], scat["outcome_pct"], 1)
                xr = np.linspace(scat["confidence"].min(), scat["confidence"].max(), 80)
                fig_s = px.scatter(scat, x="confidence", y="outcome_pct",
                                   color="analyst", color_discrete_map=ANALYST_COLORS,
                                   hover_data=["symbol","recommendation"],
                                   labels={"confidence":"Confidence","outcome_pct":"Return %"})
                fig_s.add_trace(go.Scatter(x=xr, y=np.poly1d(z)(xr),
                                           mode="lines", line=dict(color="#8b949e",dash="dash",width=1),
                                           showlegend=False, name="trend"))
                fig_s.add_hline(y=0, line_color="#30363d", line_width=1)
                fig_s.update_layout(**ply(height=290))
                st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Need more closed recommendations.")
        else:
            st.info("No closed data yet.")

    # ── Analyst × Coin heatmap ─────────────────────────────────────────────
    sec("Avg Return % — Analyst × Coin Heatmap")
    if not closed.empty:
        heat = (
            closed.dropna(subset=["outcome_pct"])
            .groupby(["analyst","symbol"])["outcome_pct"].mean()
            .reset_index()
        )
        if len(heat) >= 2:
            pivot = heat.pivot(index="analyst", columns="symbol", values="outcome_pct").fillna(0)
            fig_h = go.Figure(go.Heatmap(
                z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
                colorscale=[[0,"#ff4757"],[0.5,"#1c2333"],[1,"#00ff88"]],
                zmid=0,
                text=[[f"{v:.1f}%" for v in row] for row in pivot.values],
                texttemplate="%{text}", textfont=dict(size=11),
                colorbar=dict(tickfont=dict(color="#8b949e"),
                              title=dict(text="Avg %",font=dict(color="#8b949e"))),
            ))
            fig_h.update_layout(
                paper_bgcolor="#161b22", font=dict(color="#e6edf3"),
                margin=dict(l=70,r=20,t=15,b=60),
                height=max(180, 55 * len(pivot)),
                xaxis=dict(tickangle=-30),
            )
            st.plotly_chart(fig_h, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Need more analyst/coin combinations for heatmap.")
    else:
        st.info("No closed recommendations yet.")

    # ── Cumulative P&L ─────────────────────────────────────────────────────
    sec("Cumulative P&L Over Time")
    if not closed.empty:
        fig_cum = go.Figure()
        for analyst in analysts_sel:
            sub = closed[closed["analyst"] == analyst].sort_values("timestamp")
            if sub.empty:
                continue
            fig_cum.add_trace(go.Scatter(
                x=sub["timestamp"], y=sub["outcome_pct"].cumsum(),
                mode="lines+markers", name=analyst,
                line=dict(color=ANALYST_COLORS.get(analyst,"#58a6ff"), width=2),
                marker=dict(size=5),
            ))
        fig_cum.add_hline(y=0, line_color="#30363d", line_width=1)
        fig_cum.update_layout(**ply(height=300,
                                   yaxis=dict(title="Cumulative P&L %",**_PL["yaxis"])))
        st.plotly_chart(fig_cum, use_container_width=True, config={"displayModeBar": False})


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

def page_history():
    st.markdown("### 📋 Recommendation History")

    all_recs = load_recs()
    if all_recs.empty:
        st.info("No recommendation history yet.")
        return

    # ── Filters ────────────────────────────────────────────────────────────
    with st.expander("🔍  Filters", expanded=True):
        f1,f2,f3,f4 = st.columns(4)
        with f1: af = st.multiselect("Analyst",   ANALYST_ORDER, key="h_a")
        with f2: df_ = st.multiselect("Direction", ["LONG","SHORT","WATCH","AVOID","NEUTRAL"], key="h_d")
        with f3: sf = st.multiselect("Status",    ["OPEN","CLOSED","EXPIRED"], key="h_s")
        with f4: cf = st.multiselect("Coin",      sorted(all_recs["symbol"].unique()), key="h_c")

        d1,d2 = st.columns(2)
        with d1: date_from = st.date_input("From", value=all_recs["timestamp"].min().date(), key="h_df")
        with d2: date_to   = st.date_input("To",   value=pd.Timestamp.now().date(),          key="h_dt")

        outcome_f = st.radio("Outcome filter", ["All","Winners only","Losers only"],
                             horizontal=True, key="h_out")

    filt = all_recs.copy()
    if af:  filt = filt[filt["analyst"].isin(af)]
    if df_: filt = filt[filt["recommendation"].isin(df_)]
    if sf:  filt = filt[filt["status"].isin(sf)]
    if cf:  filt = filt[filt["symbol"].isin(cf)]
    filt = filt[(filt["timestamp"].dt.date >= date_from) & (filt["timestamp"].dt.date <= date_to)]
    if outcome_f == "Winners only": filt = filt[filt["outcome_pct"] > 0]
    if outcome_f == "Losers only":  filt = filt[filt["outcome_pct"] < 0]

    st.markdown(f"<div style='font-size:.74rem;color:#8b949e;margin-bottom:.5rem'>"
                f"Showing {len(filt)} of {len(all_recs)} recommendations</div>",
                unsafe_allow_html=True)

    if filt.empty:
        st.info("No recommendations match your filters.")
        return

    # Build display DataFrame
    disp = filt[[
        "timestamp","analyst","symbol","recommendation",
        "entry_price","close_price","outcome_pct",
        "confidence","status","thesis"
    ]].copy()

    # ── Dollar columns (handle missing position_size_usd gracefully) ──────
    _pusd_series = (
        filt["position_size_usd"]
        if "position_size_usd" in filt.columns
        else pd.Series([None] * len(filt), index=filt.index)
    )
    disp["_pos_usd"] = _pusd_series.values
    disp["_out_pct"] = disp["outcome_pct"]   # raw float before formatting

    def _fmt_pos_usd(v):
        try:
            if pd.isna(v): return "—"
            return f"${float(v):,.0f}"
        except Exception: return "—"

    def _fmt_pnl_usd_hist(row):
        try:
            pct = row["_out_pct"]
            usd = row["_pos_usd"]
            if pd.isna(pct) or pd.isna(usd): return "—"
            val = float(pct) / 100 * float(usd)
            return f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"
        except Exception: return "—"

    disp["Pos Size $"] = disp["_pos_usd"].apply(_fmt_pos_usd)
    disp["P&L $"]      = disp.apply(_fmt_pnl_usd_hist, axis=1)
    disp = disp.drop(columns=["_pos_usd", "_out_pct"])

    disp["timestamp"]   = disp["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    disp["entry_price"] = disp["entry_price"].apply(fp)
    disp["close_price"] = disp["close_price"].apply(fp)
    disp["outcome_pct"] = disp["outcome_pct"].apply(lambda x: fpc(x) if x is not None else "OPEN")
    disp["thesis"]      = disp["thesis"].apply(
        lambda x: str(x)[:90] + "…" if x and len(str(x)) > 90 else (x or "—"))
    disp.columns = ["Date","Analyst","Coin","Direction","Entry","Exit","Return %","Conf","Status","Thesis","Pos Size $","P&L $"]

    def _row_bg(row):
        try: val = float(row["Return %"].replace("%","").replace("+",""))
        except: val = 0
        if val > 0: bg = "background-color:rgba(0,255,136,.07)"
        elif val < 0: bg = "background-color:rgba(255,71,87,.07)"
        else: bg = ""
        return [bg]*len(row)

    st.dataframe(
        disp.style
            .apply(_row_bg, axis=1)
            .apply(fmt_pnl_cell_color, subset=["Return %", "P&L $"]),
        use_container_width=True, hide_index=True, height=520)

    # CSV export
    csv = filt.drop(columns=["id"], errors="ignore").to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️  Export to CSV", data=csv,
        file_name=f"analyst_recs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — COIN ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def page_coin():
    st.markdown("### 🪙 Coin Analysis")

    all_recs = load_recs()
    if all_recs.empty:
        st.info("No data yet.")
        return

    coins    = sorted(all_recs["symbol"].unique().tolist())
    selected = st.selectbox("Select coin", coins, key="coin_sel")
    if not selected:
        return

    coin_recs  = all_recs[all_recs["symbol"] == selected]
    coin_close = coin_recs[coin_recs["status"] == "CLOSED"]

    total_c   = len(coin_recs)
    closed_c  = len(coin_close)
    wins_c    = int((coin_close["outcome_pct"] > 0).sum()) if not coin_close.empty else 0
    wr_c      = round(wins_c / closed_c * 100, 1) if closed_c else 0.0
    avg_ret_c = round(float(coin_close["outcome_pct"].mean()), 2) if not coin_close.empty else 0.0
    n_analysts = coin_recs["analyst"].nunique()

    # ── KPIs ───────────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    with c1: kpi("Total Calls",    str(total_c),   f"on {selected}",               "info")
    with c2: kpi("Win Rate",       f"{wr_c}%",     f"{wins_c}/{closed_c} closed",  "pos" if wr_c>=50 else "neg")
    with c3: kpi("Avg Return",     fpc(avg_ret_c), "closed calls only",            "pos" if avg_ret_c>=0 else "neg")
    with c4: kpi("Active Analysts",str(n_analysts),f"of {len(ANALYST_ORDER)} total","info")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Price sparkline | Best analysts ────────────────────────────────────
    col_spark, col_analysts = st.columns([2, 1])

    with col_spark:
        sec(f"{selected} — 7-Day Price")
        spark = fetch_sparkline(selected, days=7)
        if spark:
            line_c = "#00ff88" if spark[-1] >= spark[0] else "#ff4757"
            fill_c = "rgba(0,255,136,.07)" if spark[-1] >= spark[0] else "rgba(255,71,87,.07)"
            fig_sp = go.Figure(go.Scatter(
                x=list(range(len(spark))), y=spark,
                mode="lines", fill="tozeroy",
                fillcolor=fill_c, line=dict(color=line_c, width=2),
            ))
            # Overlay open rec entry prices
            for _, r in coin_recs[coin_recs["status"]=="OPEN"].iterrows():
                if r.get("entry_price"):
                    fig_sp.add_hline(
                        y=r["entry_price"],
                        line_dash="dot", line_width=1,
                        line_color=ANALYST_COLORS.get(r["analyst"],"#58a6ff"),
                        annotation_text=f"{r['analyst']} entry",
                        annotation_font_color=ANALYST_COLORS.get(r["analyst"],"#58a6ff"),
                        annotation_font_size=9,
                    )
            fig_sp.update_layout(**ply(height=250, showlegend=False,
                                      xaxis=dict(visible=False),
                                      yaxis=dict(title="USD",**_PL["yaxis"])))
            st.plotly_chart(fig_sp, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"Price data unavailable for {selected}.")

    with col_analysts:
        sec("Best Analysts for this Coin")
        if not coin_close.empty:
            pa = (
                coin_close.groupby("analyst")["outcome_pct"]
                .agg(["mean","count"]).reset_index()
                .rename(columns={"mean":"Avg %","count":"Calls"})
                .sort_values("Avg %", ascending=True)
            )
            pa["Avg %"] = pa["Avg %"].round(2)
            fig_ab = go.Figure(go.Bar(
                x=pa["Avg %"], y=pa["analyst"], orientation="h",
                marker_color=["#00ff88" if v>=0 else "#ff4757" for v in pa["Avg %"]],
                text=[fpc(v) for v in pa["Avg %"]], textposition="outside",
            ))
            fig_ab.add_vline(x=0, line_color="#30363d", line_width=1)
            fig_ab.update_layout(**ply(height=250, showlegend=False,
                                      xaxis=dict(title="Avg Return %",**_PL["xaxis"])))
            st.plotly_chart(fig_ab, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No closed calls on this coin yet.")

    # ── Agreement scatter ──────────────────────────────────────────────────
    sec("Analyst Agreement vs Outcome")
    if not coin_close.empty and closed_c >= 3:
        cc = coin_close.copy()
        cc["date"] = cc["timestamp"].dt.date
        ag_rows = []
        for date, grp in cc.groupby("date"):
            top = grp["recommendation"].mode()[0]
            pct_agree = (grp["recommendation"] == top).mean() * 100
            ag_rows.append({
                "Date": date,
                "Top Direction": top,
                "Agreement %": round(pct_agree),
                "Avg Outcome %": round(float(grp["outcome_pct"].mean()), 2),
                "# Analysts": len(grp),
            })
        if ag_rows:
            ag_df = pd.DataFrame(ag_rows)
            fig_ag = px.scatter(ag_df, x="Agreement %", y="Avg Outcome %",
                                color="Top Direction",
                                color_discrete_map={"LONG":"#00ff88","SHORT":"#ff4757","WATCH":"#ffd700"},
                                size="# Analysts", hover_data=["Date"])
            fig_ag.add_hline(y=0, line_color="#30363d", line_width=1)
            fig_ag.add_vline(x=60, line_dash="dash", line_color="#484f58", line_width=1)
            fig_ag.update_layout(**ply(height=270))
            st.plotly_chart(fig_ag, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Not enough daily groupings for agreement analysis.")
    else:
        st.info(f"Need more closed {selected} calls for agreement analysis (currently {closed_c}).")

    # ── Full rec table ─────────────────────────────────────────────────────
    sec(f"All {selected} Recommendations")
    disp = coin_recs[[
        "timestamp","analyst","recommendation","entry_price",
        "target_price","stop_loss","confidence","status","outcome_pct","thesis"
    ]].copy()
    disp["timestamp"]   = disp["timestamp"].dt.strftime("%Y-%m-%d")
    disp["outcome_pct"] = disp["outcome_pct"].apply(lambda x: fpc(x) if x is not None else "OPEN")
    disp["thesis"]      = disp["thesis"].apply(lambda x: str(x)[:100]+"…" if x and len(str(x))>100 else (x or "—"))
    for col in ["entry_price","target_price","stop_loss"]:
        disp[col] = disp[col].apply(fp)
    disp.columns = ["Date","Analyst","Direction","Entry","Target","Stop","Conf","Status","Return %","Thesis"]
    st.dataframe(disp, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — LOOKBACK INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

def page_lookback():
    st.markdown("### 🧠 Lookback Insights")
    st.markdown(
        "<div style='font-size:.82rem;color:#8b949e;margin-bottom:1rem'>"
        "AI-generated post-mortems from past recommendations, stored as persistent analyst memory. "
        "Generate them with <code>/lookback BTC 30</code> in the terminal chat."
        "</div>",
        unsafe_allow_html=True,
    )

    mems = load_lookbacks()
    if mems.empty:
        st.info("No lookback reports yet.\n\nRun `/lookback BTC 30` in the analyst chat.")
        return

    coins = sorted(mems["symbol"].unique().tolist())
    sel_c = st.multiselect("Filter by coin", coins, key="lb_filter")
    if sel_c:
        mems = mems[mems["symbol"].isin(sel_c)]

    st.markdown(f"<div style='font-size:.72rem;color:#8b949e;margin-bottom:.6rem'>"
                f"{len(mems)} report(s)</div>", unsafe_allow_html=True)

    for _, row in mems.iterrows():
        ts_str = (row["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
                  if hasattr(row["generated_at"], "strftime")
                  else str(row["generated_at"])[:16])
        label = f"📊 {row['symbol']} — {row['days']}d lookback  ·  {ts_str}"
        with st.expander(label, expanded=False):
            # Render the markdown-formatted summary with proper line breaks
            summary_html = (
                str(row["summary"])
                .replace("**", "<b>", 1)
                .replace("\n**", "\n<b>")
            )
            st.markdown(
                f'<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;'
                f'padding:.9rem 1.1rem;font-size:.84rem;line-height:1.7;color:#e6edf3">'
                f'{row["summary"]}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Coverage table
    if not mems.empty:
        sec("Coverage")
        cov = (
            mems.groupby("symbol")
            .agg(Reports=("summary","count"), Latest=("generated_at","max"), Max_Days=("days","max"))
            .reset_index()
        )
        cov["Latest"] = cov["Latest"].apply(
            lambda x: x.strftime("%Y-%m-%d") if hasattr(x,"strftime") else str(x)[:10]
        )
        st.dataframe(cov, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    page = sidebar()

    dispatch = {
        "Overview":         page_overview,
        "Leaderboard":      page_leaderboard,
        "Active Positions": page_active,
        "Performance":      page_performance,
        "History":          page_history,
        "Coin Analysis":    page_coin,
        "Lookback Insights":page_lookback,
    }
    dispatch.get(page, page_overview)()

    # Footer
    st.markdown("<br>" * 2, unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;font-size:.62rem;color:#484f58;"
        "border-top:1px solid #30363d;padding-top:.9rem'>"
        "⚠️ For research purposes only — not financial advice. &nbsp;|&nbsp; "
        "Data: CoinGecko · Binance · Alternative.me"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
