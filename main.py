"""
main.py — Crypto Analyst Team: Rich terminal chat interface.

Commands:
  /analyze <COIN>         — Full 5-analyst breakdown with live data
  /team                   — Show analyst bios
  /history                — Recent recommendation history
  /performance            — Analyst track records and open positions
  /lookback <COIN> <DAYS> — Lessons-learned report → injected as memory
  /help                   — Show help

Just type naturally — mentioning a coin name (BTC, ETH, SOL…) triggers a
live data fetch and routes the question to all 5 analysts automatically.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ── Environment ────────────────────────────────────────────────────────────────
# Load .env before importing anything that might need the API key
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment

import anthropic
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from agents import ANALYST_CONFIGS, create_analyst_team
from data_fetcher import fetch_all_market_data
from tracker import (
    close_recommendation,
    get_open_recommendations,
    get_recommendations_history,
    init_db,
    get_latest_lookback_memory,
    save_recommendation,
    check_and_close_positions,
)
from performance import generate_lookback_report, generate_performance_report
from config import ANALYST_ORDER, PORTFOLIO_SIZE

# ── Setup ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)  # suppress verbose info logs
logger = logging.getLogger(__name__)
console = Console()

# ── Session cost tracker ───────────────────────────────────────────────────────
_session: Dict[str, float] = {"calls": 0.0, "est_cost_usd": 0.0}

# Per-call token cost estimates (input+output blended, ~800 in / 250 out tokens)
_COST_PER_CALL = {
    "claude-haiku-4-5-20251001": 0.00035,   # $0.25/M in + $1.25/M out → ~$0.35/1K calls
    "claude-sonnet-4-6":         0.00420,   # $3/M in + $15/M out → ~$4.20/1K calls
}

# Rich markup colour per analyst
COLOR: Dict[str, str] = {
    "ARIA": "cyan",
    "MARCUS": "yellow",
    "NOVA": "magenta",
    "VEGA": "bright_blue",
    "DELTA": "bright_cyan",
    "CHAIN": "bright_white",
    "QUANT": "bright_yellow",
    "DEFI": "bright_green",
    "ATLAS": "bright_magenta",
    "REX": "green",
    "ZEN": "red",
}

DISCLAIMER = (
    "\n[bold red]⚠️  For research purposes only — not financial advice.[/bold red]"
)

HELP_TEXT = """
[bold underline]CRYPTO ANALYST TEAM — COMMANDS[/bold underline]

  [cyan]/analyze <COIN>[/cyan]          Full 11-analyst breakdown with live data
                              e.g.  /analyze BTC
  [cyan]/team[/cyan]                    Show analyst profiles
  [cyan]/history[/cyan]                 Last 30 days of recommendations
  [cyan]/performance[/cyan]             Analyst track records + open positions
  [cyan]/lookback <COIN> <DAYS>[/cyan]  Lessons-learned report saved as memory
                              e.g.  /lookback SOL 30
  [cyan]/help[/cyan]                    Show this message

[bold underline]FREE-FORM CHAT[/bold underline]

  Just type naturally. Mentioning a coin symbol triggers a live data fetch
  and all 5 analysts respond in sequence, each seeing prior responses.

  You can also address one analyst directly:
    [dim]ARIA, what does the RSI say about ETH?[/dim]
    [dim]ZEN — give me the contrarian case for BTC[/dim]

[dim]Data: CoinGecko · Binance · Alternative.me · (yfinance fallback)[/dim]
"""

# Coins we know how to look up — derived from config to avoid drift
from config import SYMBOL_TO_CG_ID
KNOWN_COINS = list(SYMBOL_TO_CG_ID.keys())


# ─── Utilities ────────────────────────────────────────────────────────────────


def detect_coins(text: str) -> List[str]:
    """Return all recognised coin symbols found in the text (up to 3), in order."""
    upper = text.upper()
    found: List[str] = []
    for coin in KNOWN_COINS:
        # Require word boundary so "TOP" doesn't match "OP"
        if re.search(r"\b" + re.escape(coin) + r"\b", upper):
            found.append(coin)
            if len(found) >= 3:
                break
    return found


def detect_coin(text: str) -> Optional[str]:
    """Return the first recognised coin symbol found in the text, or None."""
    coins = detect_coins(text)
    return coins[0] if coins else None


def detect_addressed_analyst(text: str) -> Optional[str]:
    """
    Return an analyst name if the message is directed at one specifically
    (starts with the name, or uses @NAME or "NAME,").
    """
    upper = text.upper()
    for name in ANALYST_ORDER:
        if re.match(rf'^{name}\b', upper) or f'@{name}' in upper:
            return name
    return None


# ─── Natural language close intent ───────────────────────────────────────────

# Verb patterns that signal intent to close a position
_CLOSE_VERB_RE = re.compile(
    r'\b('
    r'close(?:\s+out)?(?:\s+(?:my|the|position|trade))?'
    r'|exit(?:\s+(?:the|my|trade))?'
    r'|take\s+profit'
    r'|stop\s+out'
    r')\b',
    re.IGNORECASE,
)


def detect_close_intent(user_input: str) -> Optional[dict]:
    """
    Detect if the user wants to close an open position via natural language.

    Returns one of:
      {"by_id": int}                          — explicit position ID
      {"symbol": "BTC", "direction": "SHORT"} — coin + direction
      {"symbol": "BTC"}                       — coin only (any open position)
      {"vague": True}                         — close intent but no identifier
      None                                    — no close intent detected
    """
    if not _CLOSE_VERB_RE.search(user_input):
        return None

    upper = user_input.upper()

    # Explicit position ID:  "close position 3", "exit trade 2", "close #7"
    id_match = re.search(r'(?:position\s+#?|trade\s+#?|#\s*)(\d+)', upper)
    if id_match:
        return {"by_id": int(id_match.group(1))}

    # Bare number after verb:  "close 3"
    num_match = re.search(r'\b(?:close|exit)\s+(\d+)\b', upper)
    if num_match:
        return {"by_id": int(num_match.group(1))}

    # Symbol + direction:  "close the BTC short", "exit my ETH long"
    symbol = detect_coin(user_input)
    dir_match = re.search(r'\b(LONG|SHORT)\b', upper)
    direction = dir_match.group(1) if dir_match else None

    if symbol and direction:
        return {"symbol": symbol, "direction": direction}
    if symbol:
        return {"symbol": symbol}

    # Intent detected but no specific position identified
    return {"vague": True}


def handle_close_intent(intent: dict) -> tuple:
    """
    Resolve a close intent against open positions in the DB and close the match.

    Returns (user_message: str, action_detail: str).
      user_message  — printed to console for the user.
      action_detail — short description injected into analyst context (empty if
                      no position was actually closed).
    """
    open_positions = get_open_recommendations()

    # ── Close by explicit ID ───────────────────────────────────────────────
    if intent.get("by_id") is not None:
        rec_id = intent["by_id"]
        match = next((p for p in open_positions if p["id"] == rec_id), None)
        if not match:
            return (f"⚠️  No open position found with ID #{rec_id}.", "")
        close_recommendation(rec_id, current_price=None)
        detail = f"{match['analyst']} {match['recommendation']} {match['symbol']} #{rec_id}"
        return (f"✅ Closed {detail} — marked as manually closed.", detail)

    # ── Close by symbol + direction ────────────────────────────────────────
    if intent.get("symbol") and intent.get("direction"):
        symbol = intent["symbol"].upper()
        direction = intent["direction"].upper()
        matches = [
            p for p in open_positions
            if p["symbol"] == symbol and p["recommendation"].upper() == direction
        ]
        if not matches:
            return (f"⚠️  No open {direction} position found for {symbol}.", "")
        if len(matches) == 1:
            rec = matches[0]
            close_recommendation(rec["id"], current_price=None)
            detail = f"{rec['analyst']} {direction} {symbol} #{rec['id']}"
            return (f"✅ Closed {detail} — marked as manually closed.", detail)
        # Multiple matching positions — ask user to pick
        lines = "\n".join(
            f"  #{p['id']} — {p['analyst']} {direction} {symbol} "
            f"(opened {p['timestamp'][:10]})"
            for p in matches
        )
        return (
            f"⚠️  Multiple open {direction} {symbol} positions found:\n{lines}\n"
            f"  Say 'close position <id>' to pick one.",
            "",
        )

    # ── Close by symbol only (any direction) ──────────────────────────────
    if intent.get("symbol"):
        symbol = intent["symbol"].upper()
        matches = [p for p in open_positions if p["symbol"] == symbol]
        if not matches:
            return (f"⚠️  No open positions found for {symbol}.", "")
        if len(matches) == 1:
            rec = matches[0]
            direction = rec["recommendation"]
            close_recommendation(rec["id"], current_price=None)
            detail = f"{rec['analyst']} {direction} {symbol} #{rec['id']}"
            return (f"✅ Closed {detail} — marked as manually closed.", detail)
        lines = "\n".join(
            f"  #{p['id']} — {p['analyst']} {p['recommendation']} {symbol} "
            f"(opened {p['timestamp'][:10]})"
            for p in matches
        )
        return (
            f"⚠️  Multiple open {symbol} positions found:\n{lines}\n"
            f"  Say 'close the {symbol} LONG/SHORT' or 'close position <id>'.",
            "",
        )

    # ── Vague intent — list everything ────────────────────────────────────
    if not open_positions:
        return ("⚠️  No open positions to close.", "")
    lines = "\n".join(
        f"  #{p['id']} — {p['analyst']} {p['recommendation']} {p['symbol']} "
        f"(opened {p['timestamp'][:10]})"
        for p in open_positions
    )
    return (
        f"Which position would you like to close?\n{lines}\n"
        f"  Say 'close position <id>' or 'close the [COIN] [LONG/SHORT]'.",
        "",
    )


# ─── Auto-close notifications ─────────────────────────────────────────────────


def _format_price(price: float) -> str:
    """Format a price nicely: more decimals for sub-$1 coins."""
    if price < 0.01:
        return f"${price:,.6f}"
    if price < 1:
        return f"${price:,.4f}"
    return f"${price:,.2f}"


def _notify_auto_closed(closed_positions: list) -> None:
    """Print Rich console notifications for auto-closed positions."""
    for pos in closed_positions:
        pnl = pos["pnl_pct"]
        sign = "+" if pnl >= 0 else ""
        outcome_color = "green" if pos["outcome"] == "WIN" else "red"

        if pos["hit_target"]:
            level_str = f"hit {_format_price(pos['target_price'])} target"
        else:
            level_str = f"hit {_format_price(pos['stop_loss'])} stop"

        console.print(
            f"[bold yellow]⚡ Auto-closed:[/bold yellow] "
            f"{pos['analyst']} {pos['direction']} {pos['symbol']} → "
            f"[{outcome_color}]{pos['outcome']} {sign}{pnl:.1f}%[/{outcome_color}] "
            f"({level_str})"
        )


# ─── Signal parser ───────────────────────────────────────────────────────────

# Matches: [SIGNAL: LONG | CONFIDENCE: 7 | TARGET: $185 | STOP: $162 | SIZE: 2.1% ($2,604) | THESIS: ...]
# The SIZE field is optional — old signals without it still parse correctly.
_SIGNAL_RE = re.compile(
    r"\[SIGNAL:\s*(?P<signal>LONG|SHORT|WATCH|AVOID|NEUTRAL)"
    r"(?:\s*\|\s*CONFIDENCE:\s*(?P<conf>\d+))?"
    r"(?:\s*\|\s*TARGET:\s*\$?(?P<target>[\d,.]+))?"
    r"(?:\s*\|\s*STOP:\s*\$?(?P<stop>[\d,.]+))?"
    r"(?:\s*\|\s*SIZE:\s*(?P<size_pct>[\d.]+)%\s*\(\$(?P<size_usd>[\d,.]+)\))?"
    r"(?:\s*\|\s*THESIS:\s*(?P<thesis>[^\]]+))?"
    r"\]",
    re.IGNORECASE,
)


def _parse_price(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_signal(
    response: str,
    analyst_name: str,
    symbol: str,
    current_price: Optional[float],
    model: str = "",
) -> None:
    """
    Extract a [SIGNAL: ...] block from an analyst response and persist
    LONG/SHORT calls to the recommendations DB. WATCH/AVOID/NEUTRAL are
    logged but not saved (no meaningful entry price or direction).
    """
    m = _SIGNAL_RE.search(response)
    if not m:
        return

    signal = m.group("signal").upper()
    conf = int(m.group("conf") or 5)
    target = _parse_price(m.group("target"))
    stop = _parse_price(m.group("stop"))
    thesis = (m.group("thesis") or "").strip()

    # SIZE field — optional, gracefully defaults to None if not present
    size_pct: Optional[float] = None
    size_usd: Optional[float] = None
    if m.group("size_pct"):
        try:
            size_pct = float(m.group("size_pct"))
        except (ValueError, TypeError):
            pass
    if m.group("size_usd"):
        try:
            size_usd = float(m.group("size_usd").replace(",", ""))
        except (ValueError, TypeError):
            pass

    logger.info(
        "Signal from %s: %s %s conf=%d target=%s stop=%s size_pct=%s size_usd=%s",
        analyst_name, signal, symbol, conf, target, stop, size_pct, size_usd,
    )

    if signal not in ("LONG", "SHORT"):
        return  # WATCH/AVOID/NEUTRAL — no DB record needed

    try:
        rec_id = save_recommendation(
            analyst=analyst_name,
            symbol=symbol,
            recommendation=signal,
            entry_price=current_price,
            target_price=target,
            stop_loss=stop,
            confidence=conf,
            thesis=thesis,
            position_size_pct=size_pct,
            position_size_usd=size_usd,
        )
        size_str = f" size={size_pct:.1f}% (${size_usd:,.0f})" if size_pct is not None else ""
        console.print(
            f"[dim]  ✦ {analyst_name} {signal} saved (id={rec_id}){size_str}[/dim]"
        )
    except Exception as exc:
        logger.warning("Failed to save signal for %s: %s", analyst_name, exc)


# ─── Display helpers ─────────────────────────────────────────────────────────


def print_header() -> None:
    console.print()
    console.print(
        Panel(
            "[bold bright_white]CRYPTO ANALYST TEAM[/bold bright_white]\n"
            "[dim]11 AI analysts · live data · distinct personalities[/dim]",
            border_style="bright_blue",
            expand=False,
            padding=(0, 4),
        )
    )
    console.print(
        "[dim]Type a question, mention a coin, or [cyan]/help[/cyan] for commands.[/dim]"
    )


def print_analyst_response(name: str, role: str, response: str) -> None:
    color = COLOR.get(name, "white")
    console.print()
    console.print(f"[bold {color}][{name} — {role}][/bold {color}]")
    console.print(response)


def print_team_bios() -> None:
    table = Table(
        title="ANALYST TEAM",
        box=box.ROUNDED,
        border_style="bright_blue",
        show_lines=True,
    )
    table.add_column("Analyst", style="bold", width=9)
    table.add_column("Role", width=18)
    table.add_column("Focus", width=52)

    for name in ANALYST_ORDER:
        cfg = ANALYST_CONFIGS[name]
        color = COLOR[name]
        table.add_row(
            f"[{color}]{name}[/{color}]",
            cfg["role"],
            cfg["focus"],
        )
    console.print()
    console.print(table)


def show_history() -> None:
    history = get_recommendations_history(days=30)
    if not history:
        console.print("[dim]No recommendations tracked in the past 30 days.[/dim]")
        return

    table = Table(
        title="RECENT RECOMMENDATIONS (30 days)",
        box=box.SIMPLE_HEAD,
        border_style="dim",
    )
    table.add_column("Date", width=11)
    table.add_column("Analyst", width=8)
    table.add_column("Symbol", width=7)
    table.add_column("Rec", width=8)
    table.add_column("Entry", width=11)
    table.add_column("Conf", width=5)
    table.add_column("Status", width=9)
    table.add_column("P/L", width=8)

    for r in history[:25]:
        color = COLOR.get(r["analyst"], "white")
        outcome_pct = r.get("outcome_pct")
        outcome_str = f"{outcome_pct:+.1f}%" if outcome_pct is not None else "—"
        outcome_color = (
            "green" if (outcome_pct or 0) > 0 else "red" if (outcome_pct or 0) < 0 else "white"
        )
        entry_price = r.get("entry_price")
        entry_str = (
            f"${entry_price:,.4f}" if entry_price and entry_price < 1
            else (f"${entry_price:,.2f}" if entry_price else "—")
        )

        table.add_row(
            r["timestamp"][:10],
            f"[{color}]{r['analyst']}[/{color}]",
            r["symbol"],
            r["recommendation"],
            entry_str,
            str(r.get("confidence", "—")),
            r["status"],
            f"[{outcome_color}]{outcome_str}[/{outcome_color}]",
        )

    console.print()
    console.print(table)


# ─── Core analysis flows ──────────────────────────────────────────────────────


def run_full_analysis(symbol: str, team: dict, client: anthropic.Anthropic, model: str = "") -> None:
    """Fetch live data and run all 5 analysts in sequence."""
    symbol = symbol.upper()
    console.print(f"\n[dim]Fetching live data for {symbol}…[/dim]")

    with console.status(f"[bold]Loading market data for {symbol}…[/bold]", spinner="dots"):
        market_data = fetch_all_market_data(symbol)

    cg = market_data.get("coingecko", {})
    current_price: Optional[float] = cg.get("price")
    if cg.get("_rate_limited"):
        console.print(f"[yellow]Warning: CoinGecko rate-limited — price data unavailable for {symbol}.[/yellow]")
    elif cg.get("error") and not current_price:
        console.print(f"[yellow]Warning: CoinGecko data unavailable for {symbol}.[/yellow]")

    # Auto-close any open positions that have hit target or stop loss
    if current_price:
        _notify_auto_closed(check_and_close_positions(symbol, current_price))

    # Inject any existing lookback memory
    memory = get_latest_lookback_memory(symbol)
    if memory:
        console.print(f"[dim italic]📚 Loaded persistent memory for {symbol}.[/dim italic]")

    question = f"Give me your full analysis of {symbol} right now based on the live data above."
    prior_responses: List[Dict[str, str]] = []

    console.print()
    console.print(Rule(f"[bold]{symbol} TEAM ANALYSIS[/bold]", style="bright_blue"))

    for name in ANALYST_ORDER:
        analyst = team[name]
        with console.status(
            f"[{COLOR[name]}]{name}[/{COLOR[name]}] analysing…", spinner="dots"
        ):
            response = analyst.analyze(question, market_data, prior_responses, memory)

        print_analyst_response(name, analyst.role, response)
        prior_responses.append({"analyst": name, "role": analyst.role, "response": response})
        parse_signal(response, name, symbol, current_price, model)
        _session["calls"] += 1
        _session["est_cost_usd"] += _COST_PER_CALL.get(model, _COST_PER_CALL["claude-sonnet-4-6"])

    console.print(DISCLAIMER)


# Words that suggest the user is asking about their positions/calls
_POSITION_QUERY_RE = re.compile(
    r'\b(position|call|trade|book|portfolio|performance|review|p[/&]l|pnl|open|holding)\b',
    re.IGNORECASE,
)


def _coins_from_open_positions() -> List[str]:
    """Return unique coin symbols from currently open positions."""
    open_recs = get_open_recommendations()
    seen: set = set()
    coins: List[str] = []
    for r in open_recs:
        sym = r.get("symbol", "").upper()
        if sym and sym not in seen:
            seen.add(sym)
            coins.append(sym)
    return coins[:3]  # cap at 3 to avoid slow fetches


def run_general_query(
    user_input: str,
    team: dict,
    client: anthropic.Anthropic,
    model: str = "",
) -> None:
    """Handle free-form questions, with optional live data if a coin is mentioned."""
    symbols = detect_coins(user_input)

    # If the user is asking about positions/calls but didn't name a coin,
    # auto-detect coins from open positions so analysts get live prices.
    if not symbols and _POSITION_QUERY_RE.search(user_input):
        symbols = _coins_from_open_positions()
        if symbols:
            console.print(
                f"[dim]No coin mentioned — loading live data for open positions: "
                f"{', '.join(symbols)}[/dim]"
            )

    primary_symbol: Optional[str] = symbols[0] if symbols else None
    addressed = detect_addressed_analyst(user_input)

    market_data = None
    if symbols:
        symbols_str = ", ".join(symbols)
        console.print(f"\n[dim]Detected {symbols_str} — fetching live data…[/dim]")
        with console.status(f"[bold]Loading {symbols_str} data…[/bold]", spinner="dots"):
            if len(symbols) == 1:
                market_data = fetch_all_market_data(symbols[0])
            else:
                # Fetch data for each detected symbol and bundle into a combined dict
                all_data: Dict[str, Any] = {}
                for sym in symbols:
                    all_data[sym] = fetch_all_market_data(sym)
                market_data = {
                    "symbol": symbols_str,
                    "multi_symbols": all_data,
                    # Top-level fields taken from primary symbol for backward compat
                    "coingecko": all_data[symbols[0]].get("coingecko", {}),
                    "fear_greed": all_data[symbols[0]].get("fear_greed", {}),
                    "funding_rate": all_data[symbols[0]].get("funding_rate"),
                    "order_book_imbalance": all_data[symbols[0]].get("order_book_imbalance"),
                    "ohlcv": all_data[symbols[0]].get("ohlcv", {}),
                    "news": all_data[symbols[0]].get("news", []),
                }

        # Auto-close open positions for every symbol whose live price was fetched
        if len(symbols) == 1:
            price = market_data.get("coingecko", {}).get("price") if market_data else None
            if price:
                _notify_auto_closed(check_and_close_positions(symbols[0], price))
        else:
            for sym in symbols:
                price = all_data[sym].get("coingecko", {}).get("price")
                if price:
                    _notify_auto_closed(check_and_close_positions(sym, price))

    # Load memory for the primary symbol (if any)
    memory: Optional[str] = None
    if primary_symbol:
        memory = get_latest_lookback_memory(primary_symbol)
        if memory:
            console.print(
                f"[dim italic]📚 Using learned memory for {primary_symbol}.[/dim italic]"
            )

    analysts_to_run = [addressed] if addressed else ANALYST_ORDER
    prior_responses: List[Dict[str, str]] = []

    console.print()
    if symbols:
        label = ", ".join(symbols)
        console.print(Rule(f"[bold]{label} ANALYSIS[/bold]", style="bright_blue"))

    for name in analysts_to_run:
        analyst = team[name]
        with console.status(
            f"[{COLOR[name]}]{name}[/{COLOR[name]}] thinking…", spinner="dots"
        ):
            try:
                if market_data:
                    response = analyst.analyze(
                        user_input, market_data, prior_responses, memory
                    )
                else:
                    response = analyst.chat(user_input, prior_responses, memory)
            except Exception as e:
                response = f"[Error: {e}]"

        print_analyst_response(name, analyst.role, response)
        prior_responses.append(
            {"analyst": name, "role": analyst.role, "response": response}
        )
        current_price = market_data.get("coingecko", {}).get("price") if market_data else None
        parse_signal(response, name, primary_symbol or "", current_price, model)
        _session["calls"] += 1
        _session["est_cost_usd"] += _COST_PER_CALL.get(model, _COST_PER_CALL["claude-sonnet-4-6"])

    console.print(DISCLAIMER)


def run_lookback(
    symbol: str,
    days: int,
    client: anthropic.Anthropic,
) -> None:
    """Generate a lookback report and save it as persistent memory."""
    console.print(
        f"\n[dim]Analysing {days} days of {symbol.upper()} recommendations…[/dim]"
    )
    with console.status("Generating lessons-learned report…", spinner="dots"):
        report = generate_lookback_report(symbol, days, client)

    console.print()
    console.print(
        Panel(
            report,
            title=f"[bold]📊 LOOKBACK: {symbol.upper()} ({days}d)[/bold]",
            border_style="dim",
            padding=(1, 2),
        )
    )
    console.print(
        "[green]✓ Memory saved — analysts will use these lessons in future prompts.[/green]"
    )


# ─── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    # ── CLI arguments ──────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="Crypto Analyst Team")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        choices=["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        help="Model to use: haiku (cheap/fast, default) or sonnet (full quality)",
    )
    args = parser.parse_args()
    model = args.model

    # Initialise database
    init_db()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print(
            Panel(
                "[bold red]ANTHROPIC_API_KEY is not set.[/bold red]\n\n"
                "1. Copy [dim].env.example[/dim] → [dim].env[/dim]\n"
                "2. Add your key:  [cyan]ANTHROPIC_API_KEY=sk-ant-...[/cyan]\n"
                "3. Re-run [cyan]python main.py[/cyan]",
                title="Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)

    # Build client and analyst team
    client = anthropic.Anthropic(api_key=api_key)
    team = create_analyst_team(client, model=model)

    # Welcome screen
    console.clear()
    print_header()
    console.print()

    # ── Chat loop ──────────────────────────────────────────────────────────
    while True:
        cost_str = f"~${_session['est_cost_usd']:.3f}" if _session["est_cost_usd"] > 0 else "$0"
        try:
            user_input = Prompt.ask(
                f"\n[bold white]You[/bold white] [dim](session {cost_str})[/dim]"
            ).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye! 📈[/dim]")
            break

        if not user_input:
            continue

        # ── Commands ───────────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd == "/help":
                console.print(HELP_TEXT)

            elif cmd == "/team":
                print_team_bios()

            elif cmd == "/analyze":
                if len(parts) < 2:
                    console.print("[red]Usage: /analyze <SYMBOL>   e.g. /analyze BTC[/red]")
                else:
                    run_full_analysis(parts[1], team, client, model=model)

            elif cmd == "/history":
                show_history()

            elif cmd == "/performance":
                with console.status("Checking current prices…", spinner="dots"):
                    report = generate_performance_report()
                console.print(report)

            elif cmd == "/lookback":
                if len(parts) < 3:
                    console.print(
                        "[red]Usage: /lookback <SYMBOL> <DAYS>   e.g. /lookback BTC 30[/red]"
                    )
                else:
                    try:
                        days = int(parts[2])
                        if days < 1:
                            raise ValueError
                    except ValueError:
                        console.print("[red]Days must be a positive integer.[/red]")
                        continue
                    run_lookback(parts[1], days, client)

            else:
                console.print(
                    f"[red]Unknown command: {cmd}[/red]  — type [cyan]/help[/cyan] for a list."
                )

        # ── Free-form query ────────────────────────────────────────────────
        else:
            # ── Natural language close detection ──────────────────────────
            # Check BEFORE handing off to analysts so the DB is updated
            # and a context note can be injected into the analyst prompt.
            action_note = ""
            close_intent = detect_close_intent(user_input)
            if close_intent:
                close_msg, action_detail = handle_close_intent(close_intent)
                console.print(f"\n{close_msg}")
                if action_detail:
                    action_note = (
                        f"USER ACTION: Position {action_detail} was just manually closed."
                    )

            # Build the message passed to analysts — prepend action note when
            # a position was actually closed so they can acknowledge it.
            analyst_input = user_input
            if action_note:
                analyst_input = f"[CONTEXT: {action_note}]\n\n{user_input}"

            run_general_query(analyst_input, team, client, model=model)


if __name__ == "__main__":
    main()
