"""
dashboard.py — Crypto Analyst Team dashboard.

A minimal, Linear/Vercel-inspired analytics UI built on Streamlit.
All rendering paths are null-safe: NaN, None and missing columns never leak
to the UI — they render as an em-dash or a contextual placeholder.

Launch:  streamlit run dashboard.py
"""

from __future__ import annotations

import base64
import functools
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from config import DB_PATH, ANALYST_ORDER, COINGECKO_BASE, SYMBOL_TO_CG_ID

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ALT_ME_BASE = "https://api.alternative.me"
AUTO_REFRESH_SEC = 60
CG_ID = SYMBOL_TO_CG_ID
EM_DASH = "—"

# Chart-series color palette (only used for plotly traces, not UI chrome).
ANALYST_COLORS: Dict[str, str] = {
    "ARIA":   "#60a5fa",
    "MARCUS": "#fbbf24",
    "NOVA":   "#c084fc",
    "VEGA":   "#38bdf8",
    "DELTA":  "#06b6d4",
    "CHAIN":  "#e4e4e7",
    "QUANT":  "#facc15",
    "DEFI":   "#34d399",
    "ATLAS":  "#f472b6",
    "REX":    "#10b981",
    "ZEN":    "#ef4444",
}

# Semantic colors.
C_POS  = "#10b981"
C_NEG  = "#ef4444"
C_WARN = "#f59e0b"
C_ACC  = "#60a5fa"
C_GRID = "#1f1f1f"
C_AXIS = "#2a2a2a"
C_TEXT = "#a1a1aa"

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG (must be first Streamlit call)
# ══════════════════════════════════════════════════════════════════════════════

_FAVICON_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect x='2' y='2' width='28' height='28' rx='6' fill='%230a0a0a' "
    "stroke='%23fafafa' stroke-width='1.5'/>"
    "<path d='M7 21 L13 14 L17 18 L25 9' fill='none' stroke='%23fafafa' "
    "stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/>"
    "</svg>"
)

st.set_page_config(
    page_title="Crypto Analyst Team",
    page_icon=_FAVICON_SVG,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# ICON SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _icon(name: str, size: int = 16, color: str = "currentColor",
          stroke: float = 1.75) -> str:
    """Return inline SVG markup for a named icon (Lucide-style, stroke-only)."""
    paths = {
        "grid":        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
                       '<rect x="14" y="3" width="7" height="7" rx="1"/>'
                       '<rect x="3" y="14" width="7" height="7" rx="1"/>'
                       '<rect x="14" y="14" width="7" height="7" rx="1"/>',
        "trophy":      '<path d="M6 4h12v4a6 6 0 0 1-12 0z"/>'
                       '<path d="M6 6H3a2 2 0 0 0 0 4h3"/>'
                       '<path d="M18 6h3a2 2 0 0 1 0 4h-3"/>'
                       '<path d="M10 14h4v3h2v3H8v-3h2z"/>',
        "pulse":       '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
        "trend-up":    '<polyline points="3 17 9 11 13 15 21 7"/>'
                       '<polyline points="15 7 21 7 21 13"/>',
        "list":        '<line x1="8" y1="6" x2="21" y2="6"/>'
                       '<line x1="8" y1="12" x2="21" y2="12"/>'
                       '<line x1="8" y1="18" x2="21" y2="18"/>'
                       '<circle cx="4" cy="6" r="1"/>'
                       '<circle cx="4" cy="12" r="1"/>'
                       '<circle cx="4" cy="18" r="1"/>',
        "hex":         '<path d="M12 2 21 7v10l-9 5-9-5V7z"/>',
        "brain":       '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 2.8A3 3 0 0 0 5 14a3 3 0 0 0 .5 3A3 3 0 0 0 9 20h.5V4H9z"/>'
                       '<path d="M15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 2.8A3 3 0 0 1 19 14a3 3 0 0 1-.5 3A3 3 0 0 1 15 20h-.5V4H15z"/>',
        "refresh":     '<polyline points="3 4 3 10 9 10"/>'
                       '<polyline points="21 20 21 14 15 14"/>'
                       '<path d="M20 10A8 8 0 0 0 6 6L3 10M21 14a8 8 0 0 1-14 4l-3-4"/>',
        "dot":         '<circle cx="12" cy="12" r="4"/>',
        "logo":        '<path d="M4 18 10 10 14 14 22 4" stroke-linecap="round" stroke-linejoin="round"/>'
                       '<line x1="3" y1="21" x2="21" y2="21" stroke-linecap="round"/>',
        "shield":      '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
        "info":        '<circle cx="12" cy="12" r="9"/>'
                       '<line x1="12" y1="16" x2="12" y2="12"/>'
                       '<line x1="12" y1="8" x2="12" y2="8"/>',
    }
    body = paths.get(name, paths["dot"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="vertical-align:-2px;display:inline-block;flex-shrink:0">{body}</svg>'
    )


# Branded logos: assets/logos/{key}.png wins over the inline SVG fallback.
_LOGO_DIR = Path(__file__).parent / "assets" / "logos"


@functools.lru_cache(maxsize=32)
def _logo_data_uri(icon_name: str) -> Optional[str]:
    for ext in ("png", "svg", "webp", "jpg", "jpeg"):
        p = _LOGO_DIR / f"{icon_name}.{ext}"
        if p.exists():
            mime = {"png": "image/png", "svg": "image/svg+xml",
                    "webp": "image/webp", "jpg": "image/jpeg",
                    "jpeg": "image/jpeg"}[ext]
            data = base64.b64encode(p.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data}"
    return None


def page_title(icon_name: str, title: str, subtitle: str = "") -> None:
    """Render the page header block (logo tile + title + optional subtitle)."""
    logo_uri = _logo_data_uri(icon_name)
    if logo_uri:
        icon_html = (
            f'<img src="{logo_uri}" alt="{title}" '
            'style="width:100%;height:100%;object-fit:contain;display:block"/>'
        )
        tile_cls = "ph-ico branded"
    else:
        icon_html = _icon(icon_name, 20, "currentColor")
        tile_cls = "ph-ico"
    sub_html = f'<div class="ph-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="ph">'
        f'<div class="{tile_cls}">{icon_html}</div>'
        f'<div class="ph-text"><div class="ph-title">{title}</div>{sub_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CSS — Linear / Vercel minimal
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg:         #0a0a0a;
    --card:       #0f0f0f;
    --card-2:     #141414;
    --elevated:   #1a1a1a;
    --border:     #1f1f1f;
    --border-2:   #262626;
    --border-3:   #3f3f46;
    --text:       #fafafa;
    --text-2:     #e4e4e7;
    --muted:      #a1a1aa;
    --dim:        #71717a;
    --subtle:     #52525b;
    --accent:     #60a5fa;
    --pos:        #10b981;
    --neg:        #ef4444;
    --warn:       #f59e0b;
    --font-sans:  'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono:  'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    --radius-sm:  4px;
    --radius:     6px;
    --radius-lg:  8px;
}

/* ── Base ─────────────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: var(--font-sans) !important;
    font-feature-settings: "cv11", "ss01";
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
.stApp, .stApp * { box-sizing: border-box; }
p, span, div, label, li { color: inherit; }

/* Kill scrollbars but keep scroll */
html, body, *, *::before, *::after {
    scrollbar-width: none !important;
    -ms-overflow-style: none !important;
}
::-webkit-scrollbar, *::-webkit-scrollbar { width: 0 !important; height: 0 !important; display: none !important; }

/* ── Hide Streamlit chrome ────────────────────────────────────────────────── */
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
[data-testid="stDeployButton"],
[data-testid="stStatusWidget"],
header [data-testid="stHeaderActionElements"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
button[title="Close sidebar"],
button[title="Open sidebar"],
#MainMenu, footer { display: none !important; }

/* Nuke any Material Symbols ligature leak */
[class*="material-symbols"], [class*="material-icons"],
span[class*="Symbol"] { font-size: 0 !important; color: transparent !important; line-height: 0 !important; }

/* ── Layout ───────────────────────────────────────────────────────────────── */
section[data-testid="stMain"] .block-container,
section.main .block-container {
    padding-top: 2.25rem !important;
    padding-bottom: 4rem !important;
    max-width: 1400px !important;
}

/* Seamless fade on rerun */
section[data-testid="stMain"] > div:first-child,
section.main > div:first-child {
    animation: fadeIn .24s cubic-bezier(.22,.61,.36,1) both;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(3px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ── Sidebar ──────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #060606 !important;
    border-right: 1px solid var(--border) !important;
    width: 240px !important;
    min-width: 240px !important;
}
[data-testid="stSidebar"] > div { padding: 1rem .75rem 0 !important; }
[data-testid="stSidebarNavLink"] { display: none !important; }

/* Brand block */
.brand {
    display: flex; align-items: center; gap: .6rem;
    padding: .35rem .25rem .85rem;
}
.brand-mark {
    width: 28px; height: 28px; border-radius: 6px;
    background: var(--text); color: var(--bg);
    display: flex; align-items: center; justify-content: center;
}
.brand-name {
    font-size: .82rem; font-weight: 600; letter-spacing: -.01em; color: var(--text);
    line-height: 1.15;
}
.brand-sub {
    font-size: .62rem; color: var(--dim); text-transform: uppercase;
    letter-spacing: .12em; margin-top: 2px; font-weight: 500;
}

.divider {
    height: 1px; background: var(--border); margin: .5rem -.25rem 1rem; border: 0;
}

/* Nav buttons (primary = active, secondary = inactive) */
[data-testid="stSidebar"] [data-testid="stButton"] > button {
    width: 100% !important;
    height: 34px !important;
    padding: 0 .7rem !important;
    margin: 1px 0 !important;
    border-radius: var(--radius) !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--muted) !important;
    font-family: var(--font-sans) !important;
    font-weight: 500 !important;
    font-size: .82rem !important;
    letter-spacing: -.005em !important;
    text-align: left !important;
    justify-content: flex-start !important;
    box-shadow: none !important;
    transition: background .15s ease, color .15s ease, border-color .15s ease !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:hover {
    background: var(--card-2) !important;
    color: var(--text) !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button p,
[data-testid="stSidebar"] [data-testid="stButton"] > button div {
    color: inherit !important; font-weight: inherit !important;
    text-align: left !important;
}
[data-testid="stSidebar"] button[kind="primary"] {
    background: var(--card-2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border-2) !important;
}

/* Refresh button in sidebar */
[data-testid="stSidebar"] button[key="refresh-now"],
[data-testid="stSidebar"] div:has(> [data-testid="stButton"]:last-of-type) [data-testid="stButton"]:last-of-type button {
    height: 32px !important;
    justify-content: center !important;
    background: transparent !important;
    border: 1px solid var(--border) !important;
    color: var(--muted) !important;
    font-size: .72rem !important;
    letter-spacing: .04em !important;
    text-transform: uppercase !important;
}

/* Live indicator */
.live-indicator {
    display: flex; align-items: center; justify-content: center; gap: .4rem;
    font-size: .68rem; color: var(--dim); letter-spacing: .06em;
    padding: .6rem 0 .4rem; font-family: var(--font-mono);
}
.live-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--pos); box-shadow: 0 0 0 3px rgba(16,185,129,.18);
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }

/* ── Page header ──────────────────────────────────────────────────────────── */
.ph {
    display: flex; align-items: center; gap: .9rem;
    padding: 0 0 1.25rem; margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}
.ph-ico {
    width: 40px; height: 40px; border-radius: 8px;
    background: var(--card-2);
    border: 1px solid var(--border-2);
    color: var(--text);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.ph-ico.branded {
    background: transparent;
    padding: 3px;
    border-color: var(--border);
}
.ph-ico.branded img { border-radius: 5px; }
.ph-title {
    font-size: 1.5rem; font-weight: 600; letter-spacing: -.02em; color: var(--text);
    line-height: 1.15;
}
.ph-sub {
    font-size: .82rem; color: var(--muted); margin-top: 3px; font-weight: 400;
    letter-spacing: -.005em;
}

/* ── KPI cards ────────────────────────────────────────────────────────────── */
.kpi {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.1rem;
    transition: border-color .15s ease;
    height: 100%;
    display: flex; flex-direction: column; justify-content: space-between;
    min-height: 98px;
}
.kpi:hover { border-color: var(--border-2); }
.kpi-label {
    font-size: .7rem; color: var(--muted); font-weight: 500;
    letter-spacing: .03em; text-transform: uppercase;
}
.kpi-val {
    font-family: var(--font-mono); font-size: 1.65rem; font-weight: 600;
    color: var(--text); line-height: 1.1; letter-spacing: -.02em;
    margin-top: .45rem;
}
.kpi-val.pos { color: var(--pos); }
.kpi-val.neg { color: var(--neg); }
.kpi-val.dim { color: var(--dim); }
.kpi-sub {
    font-size: .72rem; color: var(--dim); margin-top: .35rem;
    font-weight: 400; letter-spacing: -.005em;
}

/* ── Section heading ──────────────────────────────────────────────────────── */
.sec {
    font-size: .72rem; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: .07em;
    margin: 1.5rem 0 .75rem;
    display: flex; align-items: center; gap: .55rem;
}
.sec::after {
    content: ""; flex: 1; height: 1px; background: var(--border);
}

/* ── Empty state ──────────────────────────────────────────────────────────── */
.empty {
    border: 1px dashed var(--border-2);
    border-radius: var(--radius-lg);
    padding: 2rem 1.25rem;
    text-align: center;
    background: var(--card);
    color: var(--muted);
    font-size: .85rem;
}
.empty-title {
    font-size: .95rem; font-weight: 500; color: var(--text-2); margin-bottom: .35rem;
}

/* ── Streamlit native empty-state info/warning boxes ──────────────────────── */
[data-testid="stAlert"] {
    background: var(--card) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: var(--radius-lg) !important;
    color: var(--text-2) !important;
}
[data-testid="stAlert"] svg { color: var(--muted) !important; }

/* ── Buttons (main area) ──────────────────────────────────────────────────── */
section[data-testid="stMain"] [data-testid="stButton"] > button {
    height: 34px;
    padding: 0 .9rem;
    border-radius: var(--radius);
    background: var(--card-2);
    border: 1px solid var(--border-2);
    color: var(--text);
    font-family: var(--font-sans);
    font-weight: 500;
    font-size: .82rem;
    letter-spacing: -.005em;
    transition: background .12s ease, border-color .12s ease, transform .12s ease;
    box-shadow: none;
}
section[data-testid="stMain"] [data-testid="stButton"] > button:hover {
    background: var(--elevated);
    border-color: var(--border-3);
}
section[data-testid="stMain"] button[kind="primary"] {
    background: var(--text) !important;
    color: var(--bg) !important;
    border-color: var(--text) !important;
    font-weight: 600 !important;
}

/* ── Download button ──────────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] button {
    height: 34px;
    padding: 0 .9rem;
    border-radius: var(--radius);
    background: var(--text) !important;
    color: var(--bg) !important;
    border: 1px solid var(--text) !important;
    font-weight: 600 !important;
    font-size: .82rem !important;
}
[data-testid="stDownloadButton"] button:hover { background: var(--text-2) !important; }

/* ── Inputs (select, text, number, date) ──────────────────────────────────── */
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
    min-height: 34px !important;
    border-radius: var(--radius) !important;
    background: var(--card) !important;
    border: 1px solid var(--border-2) !important;
    color: var(--text) !important;
    font-family: var(--font-sans) !important;
    font-size: .82rem !important;
    transition: border-color .12s ease, box-shadow .12s ease !important;
    box-shadow: none !important;
}
[data-baseweb="select"] > div:hover,
[data-baseweb="input"] > div:hover { border-color: var(--border-3) !important; }
[data-baseweb="select"] > div:focus-within,
[data-baseweb="input"] > div:focus-within,
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stDateInput"] input:focus {
    border-color: var(--border-3) !important;
    box-shadow: 0 0 0 3px rgba(255,255,255,.04) !important;
    outline: none !important;
}

/* Input labels */
[data-testid="stWidgetLabel"] p,
label p {
    color: var(--muted) !important;
    font-size: .72rem !important;
    font-weight: 500 !important;
    letter-spacing: .02em !important;
    text-transform: uppercase !important;
    margin-bottom: .35rem !important;
}

/* Multiselect chips */
[data-baseweb="tag"] {
    background: var(--elevated) !important;
    border: 1px solid var(--border-2) !important;
    color: var(--text) !important;
    border-radius: var(--radius-sm) !important;
    font-size: .72rem !important;
    font-weight: 500 !important;
}

/* Dropdown chevrons */
[data-baseweb="select"] svg,
[data-baseweb="select"] svg path { fill: var(--muted) !important; transition: fill .15s ease; }
[data-baseweb="select"]:hover svg, [data-baseweb="select"]:hover svg path { fill: var(--text) !important; }

/* Popover menus */
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="menu"] {
    background: var(--elevated) !important;
    border: 1px solid var(--border-2) !important;
    border-radius: var(--radius) !important;
    box-shadow: 0 16px 36px -12px rgba(0,0,0,.6) !important;
    overflow: hidden !important;
}
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover {
    background: var(--card-2) !important;
    color: var(--text) !important;
}

/* ── Radio (inline, used for outcome filter) ──────────────────────────────── */
[data-baseweb="radio"] > div:first-child,
[data-baseweb="radio"] [role="radio"],
[data-baseweb="radio"] input[type="radio"] {
    display: none !important; width: 0 !important; height: 0 !important;
}
[data-baseweb="radio"] {
    margin: 0 6px 0 0 !important;
    padding: 5px 12px !important;
    border-radius: var(--radius) !important;
    border: 1px solid var(--border-2) !important;
    background: var(--card) !important;
    transition: all .12s ease !important;
    cursor: pointer !important;
}
[data-baseweb="radio"]:hover {
    background: var(--card-2) !important;
    border-color: var(--border-3) !important;
}
[data-baseweb="radio"] label, [data-baseweb="radio"] span {
    font-size: .78rem !important;
    color: var(--muted) !important;
    cursor: pointer !important;
}
[data-baseweb="radio"][aria-checked="true"],
label[data-baseweb="radio"]:has(input:checked) {
    background: var(--text) !important;
    border-color: var(--text) !important;
}
[data-baseweb="radio"][aria-checked="true"] label,
[data-baseweb="radio"][aria-checked="true"] span,
label[data-baseweb="radio"]:has(input:checked) span {
    color: var(--bg) !important;
    font-weight: 600 !important;
}

/* ── Expanders ────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    background: var(--card) !important;
    overflow: hidden !important;
    transition: border-color .15s ease !important;
    margin-bottom: .6rem;
}
[data-testid="stExpander"]:hover { border-color: var(--border-2) !important; }
[data-testid="stExpander"] summary,
[data-testid="stExpander"] details > summary,
[data-testid="stExpander"] button[kind="headerNoPadding"] {
    padding: .7rem 1rem !important;
    font-weight: 500 !important;
    font-size: .85rem !important;
    color: var(--text) !important;
    cursor: pointer !important;
    transition: color .12s ease !important;
    display: flex !important;
    align-items: center !important;
    gap: .55rem !important;
}
[data-testid="stExpander"] summary:hover,
[data-testid="stExpander"] button[kind="headerNoPadding"]:hover {
    color: var(--text) !important;
    background: var(--card-2) !important;
}
/* Hide any ligature text that leaks */
[data-testid="stExpander"] summary [class*="material"],
[data-testid="stExpander"] summary [class*="Material"],
[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"],
[data-testid="stExpanderToggleIcon"],
[data-testid="stExpander"] button[kind="headerNoPadding"] [class*="material"] {
    font-size: 0 !important; line-height: 0 !important; color: transparent !important;
    width: 0 !important; height: 0 !important; overflow: hidden !important;
}
/* CSS-only chevron */
[data-testid="stExpander"] summary::after,
[data-testid="stExpander"] details > summary::after {
    content: "";
    display: inline-block;
    width: 7px; height: 7px;
    border-right: 1.5px solid var(--muted);
    border-bottom: 1.5px solid var(--muted);
    transform: rotate(-45deg);
    margin-left: auto;
    transition: transform .2s ease, border-color .15s ease;
    flex-shrink: 0;
}
[data-testid="stExpander"] details[open] > summary::after {
    transform: rotate(45deg);
}
[data-testid="stExpander"] summary:hover::after { border-color: var(--text) !important; }

/* ── Tables / dataframes ──────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    overflow: hidden !important;
    background: var(--card) !important;
}
[data-testid="stDataFrame"] [role="columnheader"] {
    background: #0b0b0b !important;
    color: var(--muted) !important;
    font-family: var(--font-sans) !important;
    font-weight: 600 !important;
    font-size: .68rem !important;
    letter-spacing: .06em !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid var(--border) !important;
}
[data-testid="stDataFrame"] [role="gridcell"] {
    font-family: var(--font-mono) !important;
    font-size: .76rem !important;
    color: var(--text-2) !important;
}
[data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] {
    background: rgba(255,255,255,.015) !important;
}

/* ── Tabs ─────────────────────────────────────────────────────────────────── */
[data-baseweb="tab-list"] {
    border-bottom: 1px solid var(--border) !important;
    gap: .15rem !important;
    background: transparent !important;
}
[data-baseweb="tab"] {
    background: transparent !important;
    color: var(--muted) !important;
    border: none !important;
    padding: .55rem 1rem !important;
    font-weight: 500 !important;
    font-size: .82rem !important;
}
[data-baseweb="tab"]:hover { color: var(--text) !important; }
[data-baseweb="tab"][aria-selected="true"] {
    color: var(--text) !important;
    border-bottom: 2px solid var(--text) !important;
}

/* ── Plotly ───────────────────────────────────────────────────────────────── */
.modebar { display: none !important; }
.js-plotly-plot { border-radius: var(--radius-lg); overflow: hidden; }

/* ── Metric cards (Streamlit native) ──────────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    padding: .9rem 1rem !important;
}
[data-testid="stMetricLabel"] { color: var(--muted) !important; font-size: .7rem !important; }
[data-testid="stMetricValue"] { color: var(--text) !important; font-family: var(--font-mono) !important; }

/* ── Caption ──────────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"], .caption, small {
    color: var(--dim) !important; font-size: .72rem !important; font-weight: 400 !important;
}

/* ── Code blocks ──────────────────────────────────────────────────────────── */
code {
    font-family: var(--font-mono) !important;
    background: var(--card-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    padding: 1px 5px !important;
    font-size: .76rem !important;
    color: var(--text-2) !important;
}

/* ── Footer ───────────────────────────────────────────────────────────────── */
.site-foot {
    text-align: center; font-size: .7rem; color: var(--dim);
    border-top: 1px solid var(--border); padding-top: 1.25rem; margin-top: 2.5rem;
    font-weight: 400;
}
.site-foot span { display: inline-flex; align-items: center; gap: .35rem; }

/* ── Selection ────────────────────────────────────────────────────────────── */
::selection { background: rgba(96,165,250,.25); color: var(--text); }

/* ── Small helpers ────────────────────────────────────────────────────────── */
.pill {
    display: inline-flex; align-items: center; padding: 2px 8px;
    border-radius: 999px; font-size: .68rem; font-weight: 600;
    letter-spacing: .03em; text-transform: uppercase; font-family: var(--font-mono);
}
.pill.long  { background: rgba(16,185,129,.12); color: var(--pos); border: 1px solid rgba(16,185,129,.25); }
.pill.short { background: rgba(239,68,68,.12);  color: var(--neg); border: 1px solid rgba(239,68,68,.25); }
.pill.watch { background: rgba(245,158,11,.12); color: var(--warn); border: 1px solid rgba(245,158,11,.25); }
.pill.open  { background: var(--card-2); color: var(--muted); border: 1px solid var(--border-2); }

.mono { font-family: var(--font-mono); }
.muted { color: var(--muted); }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PLOTLY THEME (minimal, neutral palette)
# ══════════════════════════════════════════════════════════════════════════════

_PLOT_BG = "#0f0f0f"
_PLOT_FONT = dict(color=C_TEXT, family="Inter, -apple-system, sans-serif", size=11)
_PLOT_MONO = dict(family="JetBrains Mono, monospace", size=10)

_PL: Dict[str, Any] = dict(
    template="plotly_dark",
    paper_bgcolor=_PLOT_BG,
    plot_bgcolor=_PLOT_BG,
    font=_PLOT_FONT,
    margin=dict(l=48, r=18, t=24, b=42),
    xaxis=dict(gridcolor=C_GRID, zerolinecolor=C_GRID, linecolor=C_AXIS,
               tickfont=_PLOT_MONO, title_font=dict(size=11, color=C_TEXT)),
    yaxis=dict(gridcolor=C_GRID, zerolinecolor=C_GRID, linecolor=C_AXIS,
               tickfont=_PLOT_MONO, title_font=dict(size=11, color=C_TEXT)),
    legend=dict(bgcolor="rgba(15,15,15,.6)", bordercolor=C_GRID,
                font=dict(size=10, color=C_TEXT)),
    hoverlabel=dict(bgcolor="#1a1a1a", bordercolor="#3f3f46",
                    font=dict(family="JetBrains Mono, monospace", size=11,
                              color="#fafafa")),
)


def ply(**overrides) -> Dict[str, Any]:
    """Merge overrides into the base Plotly layout dict."""
    out = dict(_PL)
    for k, v in overrides.items():
        if isinstance(v, dict) and k in out and isinstance(out[k], dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

def _db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        st.error(
            f"**Database not found:** `{DB_PATH}`\n\n"
            "Run `python main.py` first to initialise the database."
        )
        st.stop()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def qdf(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        return pd.read_sql_query(sql, _db(), params=params)
    except Exception as exc:
        st.warning(f"DB query failed: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_recs(status: str = "") -> pd.DataFrame:
    if status:
        df = qdf("SELECT * FROM recommendations WHERE status = ? ORDER BY timestamp DESC",
                 params=(status,))
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
    df = qdf(
        "SELECT symbol, days, generated_at, summary FROM lookback_memory "
        "ORDER BY generated_at DESC"
    )
    if not df.empty and "generated_at" in df.columns:
        df["generated_at"] = pd.to_datetime(df["generated_at"], utc=True, errors="coerce")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# EXTERNAL DATA
# ══════════════════════════════════════════════════════════════════════════════

def _get(url: str, params: Optional[dict] = None, timeout: int = 10) -> Optional[Any]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_fg() -> Dict[str, Any]:
    data = _get(f"{ALT_ME_BASE}/fng/", {"limit": 30})
    if not data or "data" not in data:
        return {"current": None, "label": "", "history": []}
    entries = data["data"]
    try:
        return {
            "current": int(entries[0]["value"]),
            "label":   entries[0].get("value_classification", ""),
            "history": [{"ts": int(e["timestamp"]), "val": int(e["value"])}
                        for e in entries],
        }
    except Exception:
        return {"current": None, "label": "", "history": []}


@st.cache_data(ttl=60)
def fetch_prices(symbols: tuple) -> Dict[str, float]:
    if not symbols:
        return {}
    ids = ",".join(CG_ID.get(s.upper(), s.lower()) for s in symbols)
    data = _get(f"{COINGECKO_BASE}/simple/price",
                {"ids": ids, "vs_currencies": "usd"})
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


# ══════════════════════════════════════════════════════════════════════════════
# NULL-SAFE FORMAT HELPERS — single source of truth for all data rendering
# ══════════════════════════════════════════════════════════════════════════════

def present(v: Any) -> bool:
    """True if v is a non-null, non-empty, non-NaN value."""
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(v, str) and not v.strip():
        return False
    return True


def num(v: Any) -> Optional[float]:
    """Coerce v to float if it's a real number, else None."""
    if not present(v):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def fmt_price(v: Any) -> str:
    f = num(v)
    if f is None:
        return EM_DASH
    if f == 0:
        return "$0.00"
    if abs(f) < 0.001:
        return f"${f:.6f}"
    if abs(f) < 1:
        return f"${f:.4f}"
    return f"${f:,.2f}"


def fmt_pct(v: Any, sign: bool = True, digits: int = 2) -> str:
    f = num(v)
    if f is None:
        return EM_DASH
    s = "+" if (sign and f > 0) else ""
    return f"{s}{f:.{digits}f}%"


def fmt_usd(v: Any, sign: bool = False) -> str:
    f = num(v)
    if f is None:
        return EM_DASH
    if sign:
        if f > 0: return f"+${f:,.0f}"
        if f < 0: return f"-${abs(f):,.0f}"
        return "$0"
    return f"${f:,.0f}"


def fmt_int(v: Any) -> str:
    f = num(v)
    if f is None:
        return EM_DASH
    return f"{int(f):,}"


def fmt_conf(v: Any) -> str:
    f = num(v)
    if f is None:
        return EM_DASH
    return f"{f:.1f}/10"


def fmt_ts(v: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not present(v):
        return EM_DASH
    try:
        return v.strftime(fmt)
    except (ValueError, AttributeError, TypeError):
        pass
    try:
        return pd.to_datetime(v, utc=True).strftime(fmt)
    except Exception:
        return EM_DASH


def fmt_text(v: Any, fallback: str = EM_DASH,
             max_len: Optional[int] = None) -> str:
    if not present(v):
        return fallback
    s = str(v).strip()
    if max_len and len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def held_for(ts: Any) -> str:
    if not present(ts):
        return EM_DASH
    try:
        now = datetime.now(timezone.utc)
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        secs = (now - ts).total_seconds()
        if secs < 60:    return f"{int(secs)}s"
        if secs < 3600:  return f"{int(secs // 60)}m"
        if secs < 86400: return f"{int(secs // 3600)}h"
        return f"{int(secs // 86400)}d"
    except Exception:
        return EM_DASH


def unrealized_pnl_pct(rec: pd.Series, current: Any) -> Optional[float]:
    entry = num(rec.get("entry_price"))
    cur   = num(current)
    if entry is None or cur is None or entry == 0:
        return None
    direction = str(rec.get("recommendation") or "LONG").upper()
    raw = (cur - entry) / entry * 100
    return round(-raw if direction == "SHORT" else raw, 2)


def unrealized_pnl_usd(rec: pd.Series, current: Any) -> Optional[float]:
    entry = num(rec.get("entry_price"))
    cur   = num(current)
    psize = num(rec.get("position_size_usd"))
    if entry is None or cur is None or psize is None or entry == 0:
        return None
    direction = str(rec.get("recommendation") or "LONG").upper()
    raw = (cur - entry) / entry
    raw = -raw if direction == "SHORT" else raw
    return round(raw * psize, 2)


def sharpe(returns: Iterable[Any]) -> Optional[float]:
    vals = [num(r) for r in returns if num(r) is not None]
    if len(vals) < 2:
        return None
    arr = np.array(vals, dtype=float)
    sd = arr.std()
    return round(float(arr.mean() / sd), 2) if sd else None


# ══════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════

def kpi(label: str, value: str, sub: str = "", tone: str = "") -> None:
    """Render a single KPI card. tone in {'pos','neg','dim',''}."""
    cls = f"kpi-val {tone}".strip()
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="kpi">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="{cls}">{value}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def sec(title: str) -> None:
    """Render a section heading."""
    st.markdown(f'<div class="sec">{title}</div>', unsafe_allow_html=True)


def empty(title: str, hint: str = "") -> None:
    """Render a consistent empty-state block."""
    hint_html = f'<div>{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="empty">'
        f'<div class="empty-title">{title}</div>'
        f'{hint_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def direction_pill(direction: Any) -> str:
    """Return an HTML pill for LONG/SHORT/WATCH/etc."""
    s = fmt_text(direction, fallback="")
    u = s.upper()
    cls = {"LONG": "long", "SHORT": "short", "WATCH": "watch"}.get(u, "open")
    return f'<span class="pill {cls}">{s or EM_DASH}</span>'


def tone_from_num(v: Any) -> str:
    """Return CSS tone class from a numeric value."""
    f = num(v)
    if f is None or f == 0:
        return "dim"
    return "pos" if f > 0 else "neg"


def color_pnl_column(col: pd.Series) -> List[str]:
    """Per-cell text colors for a P&L string column."""
    styles = []
    for v in col:
        s = str(v) if v is not None else ""
        if s.startswith("+"):   styles.append(f"color:{C_POS}")
        elif s.startswith("-"): styles.append(f"color:{C_NEG}")
        else:                   styles.append("")
    return styles


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

NAV_ITEMS = [
    ("Overview",          "grid"),
    ("Leaderboard",       "trophy"),
    ("Active Positions",  "pulse"),
    ("Performance",       "trend-up"),
    ("History",           "list"),
    ("Coin Analysis",     "hex"),
    ("Lookback Insights", "brain"),
]


def sidebar() -> str:
    with st.sidebar:
        # Brand
        brand_svg = _icon("logo", 16, "currentColor")
        st.markdown(
            f'<div class="brand">'
            f'  <div class="brand-mark">{brand_svg}</div>'
            f'  <div>'
            f'    <div class="brand-name">Analyst Team</div>'
            f'    <div class="brand-sub">Crypto Intel</div>'
            f'  </div>'
            f'</div>'
            f'<hr class="divider"/>',
            unsafe_allow_html=True,
        )

        # Init nav state
        if "page" not in st.session_state:
            st.session_state["page"] = NAV_ITEMS[0][0]

        # Nav
        for name, _icon_key in NAV_ITEMS:
            is_active = st.session_state["page"] == name
            if st.button(
                name,
                key=f"nav-{name}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["page"] = name
                st.rerun()

        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

        # Live indicator
        if "last_refresh" not in st.session_state:
            st.session_state["last_refresh"] = time.time()
        elapsed   = time.time() - st.session_state["last_refresh"]
        remaining = max(0, AUTO_REFRESH_SEC - int(elapsed))

        st.markdown(
            f'<div class="live-indicator">'
            f'<span class="live-dot"></span>'
            f'LIVE · {remaining}s'
            f'</div>',
            unsafe_allow_html=True,
        )

        if st.button("Refresh", use_container_width=True, key="refresh-now"):
            st.cache_data.clear()
            st.session_state["last_refresh"] = time.time()
            st.rerun()

        # Auto-refresh
        if elapsed >= AUTO_REFRESH_SEC:
            st.cache_data.clear()
            st.session_state["last_refresh"] = time.time()
            st.rerun()

    return st.session_state["page"]


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def page_overview() -> None:
    page_title("grid", "Overview", "Team performance at a glance")

    all_recs = load_recs()
    if all_recs.empty:
        empty("No recommendations yet",
              "Start the analyst chat to generate calls — they'll appear here in real time.")
        return

    closed    = all_recs[all_recs["status"] == "CLOSED"]
    open_recs = all_recs[all_recs["status"] == "OPEN"]

    total_closed = len(closed)
    wins = int((closed["outcome_pct"].dropna() > 0).sum()) if not closed.empty else 0
    win_rate = round(wins / total_closed * 100, 1) if total_closed else None
    total_pnl_pct = num(closed["outcome_pct"].dropna().sum()) if not closed.empty else 0.0
    avg_conf = num(all_recs["confidence"].dropna().mean()) if "confidence" in all_recs else None

    realized_usd = 0.0
    if not closed.empty and "position_size_usd" in closed.columns:
        mask = closed["position_size_usd"].notna() & closed["outcome_pct"].notna()
        if mask.any():
            realized_usd = float(
                (closed.loc[mask, "outcome_pct"] / 100 *
                 closed.loc[mask, "position_size_usd"]).sum()
            )

    deployed_usd = 0.0
    if not open_recs.empty and "position_size_usd" in open_recs.columns:
        deployed_usd = float(open_recs["position_size_usd"].dropna().sum())

    # ── KPI row ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        tone = "dim" if win_rate is None else ("pos" if win_rate >= 50 else "neg")
        kpi("Team Win Rate",
            (f"{win_rate:.1f}%" if win_rate is not None else EM_DASH),
            f"{total_closed} closed", tone)
    with c2:
        kpi("Total Calls", fmt_int(len(all_recs)),
            f"{len(open_recs)} open · {total_closed} closed")
    with c3:
        kpi("Closed P&L %", fmt_pct(total_pnl_pct),
            "sum of outcomes", tone_from_num(total_pnl_pct))
    with c4:
        kpi("Open Positions", fmt_int(len(open_recs)), "tracked calls")
    with c5:
        kpi("Avg Confidence",
            (f"{avg_conf:.1f}/10" if avg_conf is not None else EM_DASH),
            "across all calls")

    # ── Dollar KPI row ──────────────────────────────────────────────────────
    d1, d2 = st.columns(2)
    with d1:
        kpi("Realized P&L", fmt_usd(realized_usd, sign=True),
            "closed positions w/ size", tone_from_num(realized_usd))
    with d2:
        kpi("Deployed Capital",
            fmt_usd(deployed_usd) if deployed_usd > 0 else EM_DASH,
            "sum of open position sizes")

    # ── Fear & Greed | Recent calls ─────────────────────────────────────────
    col_fg, col_right = st.columns([1, 2])

    with col_fg:
        sec("Fear & Greed")
        fg = fetch_fg()
        v = fg["current"]
        if v is None:
            empty("Fear & Greed unavailable",
                  "Live index temporarily unreachable.")
        else:
            if   v < 25: gc = C_NEG
            elif v < 45: gc = C_WARN
            elif v < 55: gc = "#eab308"
            elif v < 75: gc = "#84cc16"
            else:        gc = C_POS

            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=v,
                title={"text": fg["label"] or "",
                       "font": {"size": 12, "color": gc, "family": "Inter"}},
                gauge={
                    "axis": {"range": [0, 100], "tickcolor": C_TEXT,
                             "tickfont": {"size": 9, "color": C_TEXT}},
                    "bar": {"color": gc, "thickness": 0.2},
                    "bgcolor": "#0f0f0f",
                    "borderwidth": 0,
                    "steps": [
                        {"range": [0, 25],  "color": "rgba(239,68,68,.12)"},
                        {"range": [25, 45], "color": "rgba(245,158,11,.10)"},
                        {"range": [45, 55], "color": "rgba(234,179,8,.08)"},
                        {"range": [55, 75], "color": "rgba(132,204,22,.10)"},
                        {"range": [75, 100], "color": "rgba(16,185,129,.12)"},
                    ],
                    "threshold": {"line": {"color": gc, "width": 3},
                                  "thickness": 0.7, "value": v},
                },
                number={"font": {"size": 32, "color": gc,
                                 "family": "JetBrains Mono"}},
            ))
            fig.update_layout(height=215, paper_bgcolor=_PLOT_BG,
                              font=dict(color=C_TEXT),
                              margin=dict(l=10, r=10, t=30, b=5))
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False})

            if fg["history"]:
                hdf = pd.DataFrame(fg["history"])
                hdf["ts"] = pd.to_datetime(hdf["ts"], unit="s")
                ftr = go.Figure(go.Scatter(
                    x=hdf["ts"], y=hdf["val"],
                    fill="tozeroy", fillcolor="rgba(96,165,250,.06)",
                    line=dict(color=C_ACC, width=1.2), mode="lines",
                ))
                ftr.update_layout(
                    height=70, paper_bgcolor=_PLOT_BG, plot_bgcolor=_PLOT_BG,
                    margin=dict(l=0, r=0, t=0, b=0),
                    xaxis=dict(visible=False),
                    yaxis=dict(range=[0, 100], visible=False),
                    showlegend=False,
                )
                st.plotly_chart(ftr, use_container_width=True,
                                config={"displayModeBar": False})

    with col_right:
        sec("Recent Calls")
        disp = all_recs.head(10).copy()
        show = pd.DataFrame({
            "Time":      [fmt_ts(t, "%m-%d %H:%M") for t in disp["timestamp"]],
            "Analyst":   [fmt_text(a) for a in disp["analyst"]],
            "Coin":      [fmt_text(s) for s in disp["symbol"]],
            "Direction": [fmt_text(d) for d in disp["recommendation"]],
            "Conf":      [fmt_conf(c) for c in disp["confidence"]],
            "Status":    [fmt_text(s, fallback="") for s in disp["status"]],
            "Return":    [fmt_pct(o) if s == "CLOSED" else "OPEN"
                          for o, s in zip(disp["outcome_pct"], disp["status"])],
        })
        st.dataframe(show, use_container_width=True, hide_index=True, height=340)

        sec("Calls by Analyst")
        counts = all_recs["analyst"].value_counts().reindex(ANALYST_ORDER, fill_value=0)
        fig = go.Figure(go.Bar(
            x=counts.index, y=counts.values,
            marker_color=[ANALYST_COLORS.get(a, C_ACC) for a in counts.index],
            text=counts.values, textposition="outside",
            textfont=dict(size=10, color=C_TEXT),
        ))
        fig.update_layout(**ply(
            height=160, showlegend=False,
            yaxis=dict(visible=False, gridcolor=C_GRID, zerolinecolor=C_GRID),
            margin=dict(l=0, r=0, t=18, b=0),
        ))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

def page_leaderboard() -> None:
    page_title("trophy", "Analyst Leaderboard",
               "Ranked track records across the team")

    all_recs = load_recs()
    stats_df = load_stats()
    if all_recs.empty:
        empty("No data yet", "Leaderboard appears once the first calls are closed.")
        return

    rows: List[Dict[str, Any]] = []
    for analyst in ANALYST_ORDER:
        sub    = all_recs[all_recs["analyst"] == analyst]
        closed = sub[sub["status"] == "CLOSED"]
        outcomes = [num(o) for o in closed["outcome_pct"] if num(o) is not None]

        pnl_usd_parts: List[float] = []
        if not closed.empty and "position_size_usd" in closed.columns:
            for _, cr in closed.iterrows():
                pct = num(cr.get("outcome_pct"))
                usd = num(cr.get("position_size_usd"))
                if pct is not None and usd is not None:
                    pnl_usd_parts.append(pct / 100 * usd)
        analyst_pnl_usd = sum(pnl_usd_parts) if pnl_usd_parts else None

        st_row = stats_df[stats_df["analyst"] == analyst]
        total = int(num(st_row["total_calls"].iloc[0]) or 0) if not st_row.empty else 0
        wins  = int(num(st_row["wins"].iloc[0]) or 0)        if not st_row.empty else 0

        conf_vals = [num(c) for c in sub.get("confidence", []) if num(c) is not None]

        rows.append({
            "Analyst":      analyst,
            "Calls":        int(len(sub)),
            "Closed":       total,
            "Win Rate %":   round(wins / total * 100, 1) if total else None,
            "Avg Return %": round(float(np.mean(outcomes)), 2) if outcomes else None,
            "Best %":       round(float(max(outcomes)), 2) if outcomes else None,
            "Worst %":      round(float(min(outcomes)), 2) if outcomes else None,
            "Avg Conf":     round(float(np.mean(conf_vals)), 1) if conf_vals else None,
            "Sharpe":       sharpe(outcomes),
            "_pnl_usd":     analyst_pnl_usd,
        })

    lb = pd.DataFrame(rows)

    sort_col = st.selectbox(
        "Sort by",
        ["Win Rate %", "Avg Return %", "Sharpe", "Best %", "Calls"],
        key="lb_sort",
    )
    lb = lb.sort_values(sort_col, ascending=False,
                        na_position="last").reset_index(drop=True)
    lb.insert(0, "Rank", range(1, len(lb) + 1))

    sec("Rankings")

    disp = pd.DataFrame({
        "Rank":         lb["Rank"],
        "Analyst":      lb["Analyst"],
        "Calls":        lb["Calls"].apply(fmt_int),
        "Closed":       lb["Closed"].apply(fmt_int),
        "Win Rate %":   [fmt_pct(v, sign=False, digits=1) if v is not None else EM_DASH
                         for v in lb["Win Rate %"]],
        "Avg Return":   [fmt_pct(v) for v in lb["Avg Return %"]],
        "Best":         [fmt_pct(v) for v in lb["Best %"]],
        "Worst":        [fmt_pct(v) for v in lb["Worst %"]],
        "Avg Conf":     [(f"{v:.1f}" if v is not None else EM_DASH)
                         for v in lb["Avg Conf"]],
        "Sharpe":       [(f"{v:.2f}" if v is not None else EM_DASH)
                         for v in lb["Sharpe"]],
        "Total P&L":    [fmt_usd(v, sign=True) for v in lb["_pnl_usd"]],
    })

    st.dataframe(
        disp.style
            .apply(color_pnl_column, subset=["Avg Return", "Best", "Worst", "Total P&L"]),
        use_container_width=True, hide_index=True, height=240,
    )

    # ── Charts ──────────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        sec("Win Rate")
        wr = lb["Win Rate %"].apply(lambda v: float(v) if v is not None else 0.0)
        colors = [C_POS if (v is not None and v >= 50)
                  else C_NEG if (v is not None and v < 50)
                  else C_GRID
                  for v in lb["Win Rate %"]]
        fig = go.Figure(go.Bar(
            x=lb["Analyst"], y=wr,
            marker_color=colors,
            text=[f"{v:.0f}%" if v is not None else EM_DASH
                  for v in lb["Win Rate %"]],
            textposition="outside",
            textfont=dict(size=10, color=C_TEXT),
        ))
        fig.add_hline(y=50, line_dash="dash", line_color=C_AXIS, line_width=1)
        fig.update_layout(**ply(
            height=260, showlegend=False,
            yaxis=dict(range=[0, 115], gridcolor=C_GRID, zerolinecolor=C_GRID,
                       linecolor=C_AXIS, tickfont=_PLOT_MONO),
        ))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})

    with c2:
        sec("Avg Return")
        ar = lb["Avg Return %"].apply(lambda v: float(v) if v is not None else 0.0)
        colors = [C_POS if (v is not None and v >= 0)
                  else C_NEG if v is not None else C_GRID
                  for v in lb["Avg Return %"]]
        fig2 = go.Figure(go.Bar(
            x=lb["Analyst"], y=ar,
            marker_color=colors,
            text=[fmt_pct(v) for v in lb["Avg Return %"]],
            textposition="outside",
            textfont=dict(size=10, color=C_TEXT),
        ))
        fig2.add_hline(y=0, line_color=C_AXIS, line_width=1)
        fig2.update_layout(**ply(height=260, showlegend=False))
        st.plotly_chart(fig2, use_container_width=True,
                        config={"displayModeBar": False})

    # ── Radar ───────────────────────────────────────────────────────────────
    sec("Multi-Metric Profile")
    metrics = ["Win Rate %", "Avg Return %", "Best %", "Avg Conf", "Sharpe"]
    have_data = any(
        lb[m].dropna().shape[0] > 0 for m in metrics
    )
    if not have_data:
        empty("Not enough data for the radar chart")
    else:
        fig_r = go.Figure()
        for _, row in lb.iterrows():
            analyst = row["Analyst"]
            vals: List[float] = []
            for m in metrics:
                v = num(row[m])
                col_vals = [num(x) for x in lb[m] if num(x) is not None]
                if not col_vals or v is None:
                    vals.append(0.0)
                    continue
                mn, mx = min(col_vals), max(col_vals)
                norm = (v - mn) / (mx - mn) if mx != mn else 0.5
                vals.append(round(norm * 100, 1))
            vals.append(vals[0])

            hex_c = ANALYST_COLORS.get(analyst, C_ACC).lstrip("#")
            rgba = tuple(int(hex_c[i:i + 2], 16) for i in (0, 2, 4))
            fig_r.add_trace(go.Scatterpolar(
                r=vals, theta=metrics + [metrics[0]],
                fill="toself",
                fillcolor=f"rgba({rgba[0]},{rgba[1]},{rgba[2]},.12)",
                line=dict(color=ANALYST_COLORS.get(analyst, C_ACC), width=1.5),
                name=analyst,
            ))
        fig_r.update_layout(
            polar=dict(
                bgcolor=_PLOT_BG,
                radialaxis=dict(visible=True, range=[0, 100],
                                gridcolor=C_GRID, tickfont=dict(size=8, color=C_TEXT)),
                angularaxis=dict(gridcolor=C_GRID,
                                 tickfont=dict(size=10, color=C_TEXT)),
            ),
            paper_bgcolor=_PLOT_BG, font=dict(color=C_TEXT),
            legend=dict(bgcolor="rgba(15,15,15,.6)", bordercolor=C_GRID),
            height=380, margin=dict(l=60, r=60, t=20, b=20),
        )
        st.plotly_chart(fig_r, use_container_width=True,
                        config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — ACTIVE POSITIONS
# ══════════════════════════════════════════════════════════════════════════════

def page_active() -> None:
    page_title("pulse", "Active Positions",
               "Open recommendations, marked to live prices")

    open_recs = load_recs("OPEN")
    if open_recs.empty:
        empty("No open recommendations",
              "Generate calls via the analyst chat — they'll show up here automatically.")
        return

    syms   = tuple(open_recs["symbol"].dropna().unique().tolist())
    prices = fetch_prices(syms)

    rows: List[Dict[str, Any]] = []
    for _, rec in open_recs.iterrows():
        sym   = fmt_text(rec.get("symbol"), fallback="?")
        cur   = prices.get(sym)
        entry = num(rec.get("entry_price"))
        direction = str(rec.get("recommendation") or "LONG").upper()
        pos_usd   = num(rec.get("position_size_usd"))
        pos_pct   = num(rec.get("position_size_pct"))
        target    = num(rec.get("target_price"))
        stop      = num(rec.get("stop_loss"))
        conf      = num(rec.get("confidence"))

        pos_size_str = EM_DASH
        if pos_usd is not None:
            pos_size_str = f"${pos_usd:,.0f}"
            if pos_pct is not None:
                pos_size_str += f" · {pos_pct:.1f}%"

        unr_pct = unrealized_pnl_pct(rec, cur)
        unr_usd = unrealized_pnl_usd(rec, cur)

        pct_to_tgt = None
        pct_to_stp = None
        if cur and target:
            raw = (target - cur) / cur * 100
            pct_to_tgt = raw if direction == "LONG" else -raw
        if cur and stop:
            raw = (stop - cur) / cur * 100
            pct_to_stp = raw if direction == "LONG" else -raw

        rows.append({
            "Coin":      sym,
            "Analyst":   fmt_text(rec.get("analyst")),
            "Dir":       direction,
            "Size":      pos_size_str,
            "Entry":     fmt_price(entry),
            "Current":   fmt_price(cur) if cur is not None else EM_DASH,
            "Unreal %":  fmt_pct(unr_pct),
            "Unreal $":  fmt_usd(unr_usd, sign=True),
            "Target":    fmt_price(target),
            "Stop":      fmt_price(stop),
            "Conf":      (f"{int(conf)}/10" if conf is not None else EM_DASH),
            "Held":      held_for(rec.get("timestamp")),
            "→ Tgt":     fmt_pct(pct_to_tgt),
            "→ Stp":     fmt_pct(pct_to_stp),
            "_pnl_pct":  unr_pct,
        })

    df = pd.DataFrame(rows)

    profitable = sum(1 for r in rows if num(r["_pnl_pct"]) is not None and num(r["_pnl_pct"]) > 0)
    losing     = sum(1 for r in rows if num(r["_pnl_pct"]) is not None and num(r["_pnl_pct"]) < 0)
    longs      = sum(1 for r in rows if r["Dir"] == "LONG")
    shorts     = sum(1 for r in rows if r["Dir"] == "SHORT")
    pnl_vals   = [num(r["_pnl_pct"]) for r in rows if num(r["_pnl_pct"]) is not None]
    avg_unr    = float(np.mean(pnl_vals)) if pnl_vals else None

    # KPIs
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi("Open Positions", fmt_int(len(df)),
            f"{longs} long · {shorts} short")
    with c2:
        tone = "pos" if (len(df) and profitable >= len(df) // 2) else "neg"
        kpi("Profitable Now", fmt_int(profitable),
            f"{losing} at a loss",
            tone if len(df) else "")
    with c3:
        kpi("Avg Unrealized", fmt_pct(avg_unr),
            "across open positions", tone_from_num(avg_unr))

    sec("Open Positions")
    display = df.drop(columns=["_pnl_pct"])

    st.dataframe(
        display.style.apply(color_pnl_column, subset=["Unreal %", "Unreal $"]),
        use_container_width=True,
        hide_index=True,
        height=max(180, 38 * len(display) + 42),
    )
    st.caption("Unrealized P&L uses the most recent cached spot price. "
               "Click Refresh in the sidebar to pull fresh marks.")

    # P&L bar
    pnl_rows = [(f"{r['Coin']} · {r['Analyst']}", num(r['_pnl_pct']))
                for r in rows if num(r['_pnl_pct']) is not None]
    if pnl_rows:
        sec("Unrealized P&L by Position")
        lbls, vals = zip(*pnl_rows)
        colors = [C_POS if v >= 0 else C_NEG for v in vals]
        fig = go.Figure(go.Bar(
            x=list(lbls), y=list(vals),
            marker_color=colors,
            text=[fmt_pct(v) for v in vals],
            textposition="outside",
            textfont=dict(size=10, color=C_TEXT),
        ))
        fig.add_hline(y=0, line_color=C_AXIS, line_width=1)
        fig.update_layout(**ply(
            height=260, showlegend=False,
            xaxis=dict(tickfont=dict(size=9, color=C_TEXT),
                       gridcolor=C_GRID, zerolinecolor=C_GRID, linecolor=C_AXIS),
        ))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════

def page_performance() -> None:
    page_title("trend-up", "Performance",
               "Cumulative returns and outcome distribution over time")

    all_recs = load_recs()
    if all_recs.empty:
        empty("No performance data yet")
        return

    closed = all_recs[all_recs["status"] == "CLOSED"].copy()

    analysts_sel = st.multiselect(
        "Filter analysts", ANALYST_ORDER, default=ANALYST_ORDER, key="perf_sel"
    )
    if not analysts_sel:
        empty("Select at least one analyst",
              "Pick analysts above to populate the charts.")
        return

    # ── Cumulative win rate ─────────────────────────────────────────────────
    sec("Cumulative Win Rate Over Time")
    fig_wr = go.Figure()
    any_trace = False
    for analyst in analysts_sel:
        sub = closed[closed["analyst"] == analyst].sort_values("timestamp")
        if sub.empty:
            continue
        any_trace = True
        wins_cum  = (sub["outcome_pct"].fillna(0) > 0).cumsum()
        total_cum = pd.Series(range(1, len(sub) + 1), index=sub.index)
        fig_wr.add_trace(go.Scatter(
            x=sub["timestamp"], y=(wins_cum / total_cum * 100),
            mode="lines", name=analyst,
            line=dict(color=ANALYST_COLORS.get(analyst, C_ACC), width=1.8),
        ))
    if any_trace:
        fig_wr.add_hline(y=50, line_dash="dash", line_color=C_AXIS, line_width=1)
        fig_wr.update_layout(**ply(
            height=280,
            yaxis=dict(range=[0, 105], title="Win Rate %",
                       gridcolor=C_GRID, zerolinecolor=C_GRID,
                       linecolor=C_AXIS, tickfont=_PLOT_MONO),
        ))
        st.plotly_chart(fig_wr, use_container_width=True,
                        config={"displayModeBar": False})
    else:
        empty("No closed calls in this selection")

    # ── Volume | Confidence scatter ─────────────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        sec("Monthly Call Volume")
        monthly = all_recs.copy()
        monthly["month"] = monthly["timestamp"].dt.strftime("%Y-%m")
        mc = (
            monthly[monthly["analyst"].isin(analysts_sel)]
            .groupby(["month", "analyst"]).size().reset_index(name="n")
        )
        if not mc.empty:
            fig_m = px.bar(mc, x="month", y="n", color="analyst",
                           color_discrete_map=ANALYST_COLORS, barmode="stack")
            fig_m.update_layout(**ply(height=270))
            st.plotly_chart(fig_m, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            empty("No volume data")

    with c2:
        sec("Confidence vs Outcome")
        scat = closed[closed["analyst"].isin(analysts_sel)].dropna(
            subset=["confidence", "outcome_pct"])
        if len(scat) >= 2:
            z = np.polyfit(scat["confidence"], scat["outcome_pct"], 1)
            xr = np.linspace(scat["confidence"].min(), scat["confidence"].max(), 80)
            fig_s = px.scatter(
                scat, x="confidence", y="outcome_pct",
                color="analyst", color_discrete_map=ANALYST_COLORS,
                hover_data=["symbol", "recommendation"],
                labels={"confidence": "Confidence", "outcome_pct": "Return %"},
            )
            fig_s.add_trace(go.Scatter(
                x=xr, y=np.poly1d(z)(xr),
                mode="lines", line=dict(color=C_AXIS, dash="dash", width=1.2),
                showlegend=False, name="trend",
            ))
            fig_s.add_hline(y=0, line_color=C_AXIS, line_width=1)
            fig_s.update_layout(**ply(height=270))
            st.plotly_chart(fig_s, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            empty("Need more closed calls with confidence data")

    # ── Heatmap ─────────────────────────────────────────────────────────────
    sec("Avg Return — Analyst × Coin")
    heat = (
        closed[closed["analyst"].isin(analysts_sel)]
        .dropna(subset=["outcome_pct"])
        .groupby(["analyst", "symbol"])["outcome_pct"].mean()
        .reset_index()
    )
    if len(heat) >= 2:
        pivot = heat.pivot(index="analyst", columns="symbol",
                           values="outcome_pct").fillna(0)
        fig_h = go.Figure(go.Heatmap(
            z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
            colorscale=[[0, C_NEG], [0.5, "#0f0f0f"], [1, C_POS]],
            zmid=0,
            text=[[f"{v:.1f}%" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            textfont=dict(size=10, color=C_TEXT, family="JetBrains Mono"),
            colorbar=dict(tickfont=dict(color=C_TEXT),
                          title=dict(text="Avg %",
                                     font=dict(color=C_TEXT, size=10))),
        ))
        fig_h.update_layout(
            paper_bgcolor=_PLOT_BG, plot_bgcolor=_PLOT_BG,
            font=dict(color=C_TEXT),
            margin=dict(l=70, r=20, t=20, b=60),
            height=max(180, 55 * len(pivot)),
            xaxis=dict(tickangle=-30),
        )
        st.plotly_chart(fig_h, use_container_width=True,
                        config={"displayModeBar": False})
    else:
        empty("Need more analyst × coin combinations")

    # ── Cumulative P&L ──────────────────────────────────────────────────────
    sec("Cumulative P&L %")
    fig_cum = go.Figure()
    any_trace = False
    for analyst in analysts_sel:
        sub = closed[closed["analyst"] == analyst].sort_values("timestamp")
        if sub.empty:
            continue
        any_trace = True
        fig_cum.add_trace(go.Scatter(
            x=sub["timestamp"], y=sub["outcome_pct"].fillna(0).cumsum(),
            mode="lines+markers", name=analyst,
            line=dict(color=ANALYST_COLORS.get(analyst, C_ACC), width=1.8),
            marker=dict(size=4),
        ))
    if any_trace:
        fig_cum.add_hline(y=0, line_color=C_AXIS, line_width=1)
        fig_cum.update_layout(**ply(
            height=280,
            yaxis=dict(title="Cumulative P&L %", gridcolor=C_GRID,
                       zerolinecolor=C_GRID, linecolor=C_AXIS,
                       tickfont=_PLOT_MONO),
        ))
        st.plotly_chart(fig_cum, use_container_width=True,
                        config={"displayModeBar": False})
    else:
        empty("No closed calls to plot")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def page_history() -> None:
    page_title("list", "Recommendation History",
               "Full journal of every call, filterable and exportable")

    all_recs = load_recs()
    if all_recs.empty:
        empty("No recommendation history yet",
              "History populates automatically as calls are generated.")
        return

    with st.expander("Filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            af = st.multiselect("Analyst", ANALYST_ORDER, key="h_a")
        with f2:
            df_ = st.multiselect("Direction",
                                 ["LONG", "SHORT", "WATCH", "AVOID", "NEUTRAL"],
                                 key="h_d")
        with f3:
            sf = st.multiselect("Status",
                                ["OPEN", "CLOSED", "EXPIRED"], key="h_s")
        with f4:
            cf = st.multiselect("Coin",
                                sorted(all_recs["symbol"].dropna().unique()),
                                key="h_c")

        d1, d2 = st.columns(2)
        ts_min = all_recs["timestamp"].min()
        min_date = ts_min.date() if present(ts_min) else datetime.utcnow().date()
        with d1:
            date_from = st.date_input("From", value=min_date, key="h_df")
        with d2:
            date_to = st.date_input("To",
                                    value=pd.Timestamp.now().date(), key="h_dt")

        outcome_f = st.radio("Outcome",
                             ["All", "Winners", "Losers"],
                             horizontal=True, key="h_out")

    filt = all_recs.copy()
    if af:  filt = filt[filt["analyst"].isin(af)]
    if df_: filt = filt[filt["recommendation"].isin(df_)]
    if sf:  filt = filt[filt["status"].isin(sf)]
    if cf:  filt = filt[filt["symbol"].isin(cf)]
    filt = filt[filt["timestamp"].notna()]
    filt = filt[(filt["timestamp"].dt.date >= date_from) &
                (filt["timestamp"].dt.date <= date_to)]
    if outcome_f == "Winners":
        filt = filt[filt["outcome_pct"].fillna(0) > 0]
    elif outcome_f == "Losers":
        filt = filt[filt["outcome_pct"].fillna(0) < 0]

    st.markdown(
        f'<div style="font-size:.74rem;color:var(--muted);margin:.5rem 0 .75rem">'
        f'Showing <span class="mono" style="color:var(--text)">{len(filt)}</span> '
        f'of <span class="mono" style="color:var(--text)">{len(all_recs)}</span> '
        f'recommendations</div>',
        unsafe_allow_html=True,
    )

    if filt.empty:
        empty("No matches", "Try clearing a filter or expanding the date range.")
        return

    # Build display DataFrame
    disp = pd.DataFrame({
        "Date":      [fmt_ts(t, "%Y-%m-%d %H:%M") for t in filt["timestamp"]],
        "Analyst":   [fmt_text(a) for a in filt["analyst"]],
        "Coin":      [fmt_text(s) for s in filt["symbol"]],
        "Direction": [fmt_text(d) for d in filt["recommendation"]],
        "Entry":     [fmt_price(v) for v in filt["entry_price"]],
        "Exit":      [(fmt_price(v) if present(v) else "OPEN")
                      for v in filt["close_price"]],
        "Return":    [(fmt_pct(v) if present(v) else "OPEN")
                      for v in filt["outcome_pct"]],
        "Conf":      [fmt_conf(c) for c in filt["confidence"]],
        "Status":    [fmt_text(s, fallback="") for s in filt["status"]],
        "Size":      [(f"${num(v):,.0f}" if num(v) is not None else EM_DASH)
                      for v in filt.get("position_size_usd",
                                        pd.Series([None]*len(filt)))],
        "P&L $":     [
            (lambda pct, usd: (
                fmt_usd(pct / 100 * usd, sign=True)
                if num(pct) is not None and num(usd) is not None else EM_DASH
            ))(filt.iloc[i].get("outcome_pct"),
               filt.iloc[i].get("position_size_usd")
               if "position_size_usd" in filt.columns else None)
            for i in range(len(filt))
        ],
        "Thesis":    [fmt_text(t, fallback=EM_DASH, max_len=90)
                      for t in filt["thesis"]],
    })

    st.dataframe(
        disp.style.apply(color_pnl_column, subset=["Return", "P&L $"]),
        use_container_width=True, hide_index=True, height=520,
    )

    csv = filt.drop(columns=["id"], errors="ignore").to_csv(index=False).encode("utf-8")
    st.download_button(
        "Export CSV", data=csv,
        file_name=f"analyst_recs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — COIN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def page_coin() -> None:
    page_title("hex", "Coin Analysis",
               "Drill into per-asset analyst coverage and outcomes")

    all_recs = load_recs()
    if all_recs.empty:
        empty("No coin data yet")
        return

    coins = sorted(all_recs["symbol"].dropna().unique().tolist())
    if not coins:
        empty("No coin data yet")
        return

    selected = st.selectbox("Select coin", coins, key="coin_sel")
    if not selected:
        return

    coin_recs  = all_recs[all_recs["symbol"] == selected]
    coin_close = coin_recs[coin_recs["status"] == "CLOSED"]

    total_c   = len(coin_recs)
    closed_c  = len(coin_close)
    wins_c    = int((coin_close["outcome_pct"].dropna() > 0).sum()) if not coin_close.empty else 0
    wr_c      = (wins_c / closed_c * 100) if closed_c else None
    avg_ret_c = num(coin_close["outcome_pct"].dropna().mean()) if not coin_close.empty else None
    n_analysts = coin_recs["analyst"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("Total Calls", fmt_int(total_c), f"on {selected}")
    with c2:
        tone = "pos" if (wr_c is not None and wr_c >= 50) else "neg" if wr_c is not None else "dim"
        kpi("Win Rate",
            (f"{wr_c:.1f}%" if wr_c is not None else EM_DASH),
            f"{wins_c}/{closed_c} closed", tone)
    with c3:
        kpi("Avg Return", fmt_pct(avg_ret_c), "closed calls",
            tone_from_num(avg_ret_c))
    with c4:
        kpi("Active Analysts", fmt_int(n_analysts),
            f"of {len(ANALYST_ORDER)} total")

    # Price sparkline | Best analysts
    col_spark, col_analysts = st.columns([2, 1])

    with col_spark:
        sec(f"{selected} — 7-Day Price")
        spark = fetch_sparkline(selected, days=7)
        if spark and len(spark) >= 2:
            up = spark[-1] >= spark[0]
            line_c = C_POS if up else C_NEG
            fill_c = "rgba(16,185,129,.08)" if up else "rgba(239,68,68,.08)"
            fig_sp = go.Figure(go.Scatter(
                x=list(range(len(spark))), y=spark,
                mode="lines", fill="tozeroy",
                fillcolor=fill_c, line=dict(color=line_c, width=1.8),
            ))
            # Open-position entry overlays
            for _, r in coin_recs[coin_recs["status"] == "OPEN"].iterrows():
                entry_v = num(r.get("entry_price"))
                if entry_v is not None:
                    fig_sp.add_hline(
                        y=entry_v, line_dash="dot", line_width=1,
                        line_color=ANALYST_COLORS.get(r["analyst"], C_ACC),
                        annotation_text=f"{r['analyst']}",
                        annotation_font_color=ANALYST_COLORS.get(r["analyst"], C_ACC),
                        annotation_font_size=9,
                    )
            fig_sp.update_layout(**ply(
                height=260, showlegend=False,
                xaxis=dict(visible=False),
                yaxis=dict(title="USD", gridcolor=C_GRID, zerolinecolor=C_GRID,
                           linecolor=C_AXIS, tickfont=_PLOT_MONO),
            ))
            st.plotly_chart(fig_sp, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            empty(f"Price data unavailable for {selected}")

    with col_analysts:
        sec("Best Analysts")
        if not coin_close.empty:
            pa = (
                coin_close.dropna(subset=["outcome_pct"])
                .groupby("analyst")["outcome_pct"]
                .agg(["mean", "count"]).reset_index()
                .rename(columns={"mean": "Avg %", "count": "Calls"})
                .sort_values("Avg %", ascending=True)
            )
            if pa.empty:
                empty("No closed calls yet")
            else:
                pa["Avg %"] = pa["Avg %"].round(2)
                colors = [C_POS if v >= 0 else C_NEG for v in pa["Avg %"]]
                fig_ab = go.Figure(go.Bar(
                    x=pa["Avg %"], y=pa["analyst"], orientation="h",
                    marker_color=colors,
                    text=[fmt_pct(v) for v in pa["Avg %"]],
                    textposition="outside",
                    textfont=dict(size=10, color=C_TEXT),
                ))
                fig_ab.add_vline(x=0, line_color=C_AXIS, line_width=1)
                fig_ab.update_layout(**ply(
                    height=260, showlegend=False,
                    xaxis=dict(title="Avg Return %", gridcolor=C_GRID,
                               zerolinecolor=C_GRID, linecolor=C_AXIS,
                               tickfont=_PLOT_MONO),
                ))
                st.plotly_chart(fig_ab, use_container_width=True,
                                config={"displayModeBar": False})
        else:
            empty("No closed calls on this coin yet")

    # Agreement scatter
    sec("Daily Analyst Agreement vs Outcome")
    if not coin_close.empty and closed_c >= 3:
        cc = coin_close.copy()
        cc["date"] = cc["timestamp"].dt.date
        ag_rows: List[Dict[str, Any]] = []
        for date, grp in cc.groupby("date"):
            if grp["recommendation"].dropna().empty:
                continue
            top = grp["recommendation"].mode().iloc[0]
            pct_agree = (grp["recommendation"] == top).mean() * 100
            avg_out = num(grp["outcome_pct"].dropna().mean())
            ag_rows.append({
                "Date":          date,
                "Top Direction": top,
                "Agreement %":   round(pct_agree),
                "Avg Outcome %": round(avg_out, 2) if avg_out is not None else 0.0,
                "# Analysts":    int(len(grp)),
            })
        if ag_rows:
            ag_df = pd.DataFrame(ag_rows)
            fig_ag = px.scatter(
                ag_df, x="Agreement %", y="Avg Outcome %",
                color="Top Direction",
                color_discrete_map={"LONG": C_POS, "SHORT": C_NEG, "WATCH": C_WARN},
                size="# Analysts", hover_data=["Date"],
            )
            fig_ag.add_hline(y=0, line_color=C_AXIS, line_width=1)
            fig_ag.add_vline(x=60, line_dash="dash", line_color=C_AXIS, line_width=1)
            fig_ag.update_layout(**ply(height=270))
            st.plotly_chart(fig_ag, use_container_width=True,
                            config={"displayModeBar": False})
        else:
            empty("Not enough daily groupings for agreement analysis")
    else:
        empty(f"Need ≥3 closed {selected} calls (currently {closed_c})")

    # Full table
    sec(f"All {selected} Recommendations")
    disp = pd.DataFrame({
        "Date":       [fmt_ts(t, "%Y-%m-%d") for t in coin_recs["timestamp"]],
        "Analyst":    [fmt_text(a) for a in coin_recs["analyst"]],
        "Direction":  [fmt_text(d) for d in coin_recs["recommendation"]],
        "Entry":      [fmt_price(v) for v in coin_recs["entry_price"]],
        "Target":     [fmt_price(v) for v in coin_recs["target_price"]],
        "Stop":       [fmt_price(v) for v in coin_recs["stop_loss"]],
        "Conf":       [fmt_conf(c) for c in coin_recs["confidence"]],
        "Status":     [fmt_text(s, fallback="") for s in coin_recs["status"]],
        "Return":     [(fmt_pct(v) if present(v) else "OPEN")
                       for v in coin_recs["outcome_pct"]],
        "Thesis":     [fmt_text(t, fallback=EM_DASH, max_len=100)
                       for t in coin_recs["thesis"]],
    })
    st.dataframe(
        disp.style.apply(color_pnl_column, subset=["Return"]),
        use_container_width=True, hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — LOOKBACK INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════

def page_lookback() -> None:
    page_title("brain", "Lookback Insights",
               "Post-mortems from closed calls, persisted as analyst memory")

    st.markdown(
        '<div style="font-size:.82rem;color:var(--muted);'
        'margin:-.2rem 0 1.25rem;line-height:1.6">'
        'Reports summarize lessons from closed positions and are injected into '
        'future prompts. Generate new ones with <code>/lookback BTC 30</code> '
        'in the terminal chat.'
        '</div>',
        unsafe_allow_html=True,
    )

    mems = load_lookbacks()
    if mems.empty:
        empty("No lookback reports yet",
              "Run /lookback SYMBOL DAYS in the analyst chat to create one.")
        return

    coins = sorted(mems["symbol"].dropna().unique().tolist())
    sel_c = st.multiselect("Filter by coin", coins, key="lb_filter")
    if sel_c:
        mems = mems[mems["symbol"].isin(sel_c)]

    if mems.empty:
        empty("No reports match your filter")
        return

    st.markdown(
        f'<div style="font-size:.68rem;color:var(--muted);margin-bottom:.85rem;'
        f'letter-spacing:.08em;font-weight:500;text-transform:uppercase">'
        f'{len(mems)} report{"s" if len(mems) != 1 else ""}</div>',
        unsafe_allow_html=True,
    )

    for _, row in mems.iterrows():
        sym = fmt_text(row.get("symbol"), fallback="?")
        days = num(row.get("days"))
        days_str = f"{int(days)}-day" if days is not None else "—"
        ts_str = fmt_ts(row.get("generated_at"), "%Y-%m-%d %H:%M UTC")
        label = f"{sym}  ·  {days_str} lookback  ·  {ts_str}"
        summary = fmt_text(row.get("summary"), fallback="(empty report)")
        with st.expander(label, expanded=False):
            # Escape HTML chars minimally (preserve pre-formatted text)
            safe = (summary.replace("&", "&amp;")
                           .replace("<", "&lt;")
                           .replace(">", "&gt;"))
            st.markdown(
                f'<div style="font-size:.85rem;line-height:1.75;'
                f'color:var(--text-2);white-space:pre-wrap;'
                f'font-family:var(--font-sans)">{safe}</div>',
                unsafe_allow_html=True,
            )

    sec("Coverage")
    cov = (
        mems.groupby("symbol")
            .agg(Reports=("summary", "count"),
                 Latest=("generated_at", "max"),
                 Max_Days=("days", "max"))
            .reset_index()
            .rename(columns={"symbol": "Coin"})
    )
    cov["Latest"] = cov["Latest"].apply(lambda v: fmt_ts(v, "%Y-%m-%d"))
    cov["Reports"] = cov["Reports"].apply(fmt_int)
    cov["Max_Days"] = cov["Max_Days"].apply(lambda v: f"{int(v)}d" if num(v) is not None else EM_DASH)
    cov = cov.rename(columns={"Max_Days": "Max Days"})
    st.dataframe(cov, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    page = sidebar()

    dispatch = {
        "Overview":          page_overview,
        "Leaderboard":       page_leaderboard,
        "Active Positions":  page_active,
        "Performance":       page_performance,
        "History":           page_history,
        "Coin Analysis":     page_coin,
        "Lookback Insights": page_lookback,
    }
    dispatch.get(page, page_overview)()

    # Footer
    st.markdown(
        '<div class="site-foot">'
        '<span>Research only · not financial advice</span>'
        '<span style="margin:0 .75rem;color:var(--border-2)">·</span>'
        '<span>CoinGecko · Binance · Deribit · DeFiLlama · Alternative.me</span>'
        '</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
