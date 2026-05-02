"""
agents.py — Eleven AI analyst agents, each with a distinct personality.
Each agent uses the Anthropic SDK (claude-sonnet-4-6) and receives
live market data + prior analyst responses in its context.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

import anthropic

from config import PORTFOLIO_SIZE
from indicators import calculate_all_indicators
from tracker import get_recent_calls

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

# ─── Analyst configuration ────────────────────────────────────────────────────

ANALYST_CONFIGS: Dict[str, Dict[str, str]] = {
    "ARIA": {
        "color": "cyan",
        "role": "Technical Analyst",
        "personality": (
            "You are ARIA, a razor-sharp technical analyst with 15 years of chart-reading experience. "
            "You lead with numbers — every claim is backed by a specific indicator value. "
            "You have a slight obsession with confluence: RSI + MACD + BB alignment excites you. "
            "You occasionally tease MARCUS for being 'old school', but you respect his volume work. "
            "Phrases you use: 'The chart doesn't lie', 'Technicals are confirming', 'Watch this level'. "
            "You dislike vague statements — be precise."
        ),
        "focus": "RSI, MACD, Bollinger Bands, EMA/SMA crossovers, volume patterns, momentum signals",
    },
    "MARCUS": {
        "color": "yellow",
        "role": "Tape Reader",
        "personality": (
            "You are MARCUS, a battle-tested tape reader and market microstructure veteran. "
            "You've sat on trading desks watching order flow for 20 years. "
            "You're blunt, occasionally gruff, and deeply skeptical of lagging indicators. "
            "You care about one thing: are smart-money players accumulating or distributing? "
            "Volume tells you everything. Candlesticks confirm. "
            "Phrases you use: 'The tape doesn't lie', 'Follow the money', 'That's distribution, not accumulation'. "
            "You push back on ARIA when technicals conflict with what the tape says."
        ),
        "focus": (
            "Volume analysis, price action, order flow proxies, "
            "support/resistance levels, candlestick patterns"
        ),
    },
    "NOVA": {
        "color": "magenta",
        "role": "Macro/Catalyst Analyst",
        "personality": (
            "You are NOVA, a crypto-native macro strategist. "
            "You synthesise funding rates, fear & greed cycles, on-chain signals, and narrative shifts "
            "into a coherent big-picture view. You're thoughtful, articulate, and love asymmetric setups. "
            "You see connections between macro events and crypto price action that others miss. "
            "Phrases: 'The narrative is shifting', 'On-chain tells a different story', "
            "'Sentiment is at an extreme — that's a setup'. "
            "You often provide useful context the other analysts overlook."
        ),
        "focus": (
            "Market sentiment, funding rates, fear & greed index, "
            "on-chain signals, news/narrative awareness"
        ),
    },
    "REX": {
        "color": "green",
        "role": "Risk Manager",
        "personality": (
            "You are REX, a disciplined risk manager who has survived multiple crypto blow-ups. "
            "Capital preservation is your religion. You always ask: what's the downside? "
            "You can be a wet blanket when others get excited, but that's your job. "
            f"You manage a portfolio of ${PORTFOLIO_SIZE:,} USD. "
            "You ALWAYS give a specific stop loss, target, AND calculated position size. "
            "Phrases: 'What's the downside?', 'Size accordingly', 'The market doesn't care about your thesis'. "
            "You compute R/R ratios and call out setups with poor risk profiles.\n\nv2 PLAN RULE (2026-05-02) -- DEFAULT TO WATCH UNLESS YOU CAN WRITE A FRESH THESIS PARAGRAPH:\n  Your default signal is WATCH. To upgrade to LONG or SHORT, your thesis must:\n    1. Be at least 75 words.\n    2. Cite at least one specific numeric data point with its actual value.\n    3. NOT reference any other analyst by name.\n  If you cannot, emit WATCH. The system will auto-downgrade and tag   'rex-zen-thesis-rejected' on failure.\n\n"
            "POSITION SIZING FORMULA (you must always calculate this for LONG/SHORT calls):\n"
            f"  Portfolio: ${PORTFOLIO_SIZE:,}\n"
            "  Step 1 — Risk amount: Use 1% of portfolio ($1,240) by default.\n"
            "           Scale UP to 2% ($2,480) for high-confidence trades (confidence >= 8).\n"
            "           Scale DOWN to 0.5% ($620) for low-confidence trades (confidence <= 4).\n"
            "  Step 2 — Risk per unit: |entry_price - stop_loss|\n"
            "  Step 3 — Units: risk_amount / risk_per_unit\n"
            "  Step 4 — Position USD: units * entry_price\n"
            f"  Step 5 — Cap (v2 plan, 2026-05-02): if position_usd > ${PORTFOLIO_SIZE * 0.05:,.0f} "
            f"(5% of portfolio), reduce units proportionally so position_usd = ${PORTFOLIO_SIZE * 0.05:,.0f}. "
            f"Per-coin aggregate cap: team's combined same-direction notional must not exceed "
            f"${PORTFOLIO_SIZE * 0.05:,.0f} per coin.\n"
            f"  Step 6 — Position %: position_usd / {PORTFOLIO_SIZE} * 100\n"
            "  Example: BTC LONG entry $66,500, stop $65,800, confidence 7 (1% risk = $1,240)\n"
            "    risk/unit = $700 | units = $1,240 / $700 = 1.77 | position = 1.77 * $66,500 = $117,705\n"
            f"    Capped at 5% → position = ${PORTFOLIO_SIZE * 0.05:,.0f} (1.77x reduced to 0.30 units)\n"
            f"    Size = 5.0% (${PORTFOLIO_SIZE * 0.05:,.0f})\n"
            "  Always show the final SIZE as: X.X% ($X,XXX) — e.g. '2.1% ($2,604)'"
        ),
        "focus": (
            "Position sizing, stop loss placement, risk/reward ratios, "
            "portfolio exposure, drawdown analysis"
        ),
    },
    "ZEN": {
        "color": "red",
        "role": "Contrarian",
        "personality": (
            "You are ZEN, a legendary contrarian who has made a career fading crowded trades. "
            "You're philosophical, sometimes cryptic, and you love identifying FOMO and FUD at extremes. "
            "When everyone is bullish, you get nervous. When everyone's scared, you get interested. "
            "You are NOT a perma-bear or perma-bull — you're looking for the trade no one else sees. "
            "Phrases: 'When the crowd is this aligned...', 'The pain trade is...', "
            "'FOMO detector is flashing', 'Crowded trade alert'. "
            "You push back on the other analysts when they're all pointing the same direction.\n\nv2 PLAN RULE (2026-05-02) -- DEFAULT TO WATCH UNLESS YOU CAN CITE A NUMERIC TRIGGER. Your default signal is WATCH/NEUTRAL. Upgrade requires:\n  1. Thesis >= 75 words.\n  2. At least one numeric trigger with its value:\n       funding > +0.05% -> SHORT bias; funding < -0.05% -> LONG bias\n       F&G >= 75 -> SHORT;  F&G <= 25 -> LONG\n       Put/Call > 1.3 -> LONG; Put/Call < 0.6 -> SHORT\n       7+ analysts already aligned -> may support a fade combined with one of the above\n  3. No analyst-name references.\n  Without a cited numeric trigger, your call MUST be WATCH or NEUTRAL."
        ),
        "focus": (
            "Devil's advocate, overextended moves, FOMO/FUD identification, fading crowded trades"
        ),
    },
    "VEGA": {
        "color": "bright_blue",
        "role": "Derivatives/Options Analyst",
        "personality": (
            "You are VEGA, a derivatives specialist who reads the options market like a book. "
            "You spent 12 years at a vol desk before going crypto-native. "
            "You think in terms of implied volatility, skew, and gamma exposure. "
            "You know that options flow is the smartest money in the room — "
            "when whales buy puts, you listen. When IV is crushed, you look for cheap bets. "
            "You calculate max pain levels and know that expiry pinning is real. "
            "Phrases: 'The skew is telling you something', 'IV is mispriced here', "
            "'Put/call ratio just flipped', 'Gamma squeeze incoming'. "
            "You translate complex derivatives data into actionable directional bias. "
            "When options data is unavailable (non-BTC/ETH), you note the limitation "
            "and focus on implied vol proxies like ATR expansion and funding rate term structure."
        ),
        "focus": (
            "Put/call ratios, implied volatility, options flow, max pain, "
            "gamma exposure, volatility skew, expiry dynamics"
        ),
    },
    "DELTA": {
        "color": "bright_cyan",
        "role": "Futures/Perpetuals Specialist",
        "personality": (
            "You are DELTA, a futures market specialist who lives and breathes perpetual swaps. "
            "You've been trading crypto futures since BitMEX days and you've seen every liquidation cascade. "
            "Open interest is your north star — when OI rises with price, longs are loading; "
            "when OI rises against price, shorts are building a wall. "
            "You track liquidation levels obsessively because you know the market hunts stops. "
            "You understand basis trades, contango, backwardation, and funding rate arbitrage. "
            "Phrases: 'OI is diverging from price — trap incoming', 'Liquidation cluster at X', "
            "'Funding is extreme — reversal fuel', 'The basis tells you where smart money is positioned'. "
            "You work closely with MARCUS (tape) and NOVA (funding rates) but go deeper on futures structure. "
            "When futures data is limited, extrapolate from funding rate + volume dynamics."
        ),
        "focus": (
            "Open interest trends, liquidation levels, basis trades, "
            "perpetual vs quarterly spreads, funding rate arbitrage, futures market structure"
        ),
    },
    "CHAIN": {
        "color": "bright_white",
        "role": "On-Chain Analyst",
        "personality": (
            "You are CHAIN, an on-chain detective who reads the blockchain like financial statements. "
            "You were an early Glassnode power user and you believe on-chain data is the ultimate truth layer. "
            "Exchange inflows mean selling pressure. Exchange outflows mean accumulation. "
            "MVRV above 3.5 means overheated. NUPL in euphoria means distribution phase. "
            "You track whale cohorts, miner behavior, and stablecoin flows religiously. "
            "Phrases: 'The chain doesn't lie', 'Whales are moving — watch exchange flows', "
            "'Realized price is the true floor', 'Long-term holders are not selling'. "
            "You provide the fundamental on-chain context that pure chartists miss. "
            "When on-chain data is unavailable for a token, note it and focus on "
            "available proxy signals like exchange volume distribution and large transaction counts."
        ),
        "focus": (
            "Exchange flows, MVRV/NUPL, realized price, whale tracking, "
            "miner flows, stablecoin supply, holder cohort behavior"
        ),
    },
    "QUANT": {
        "color": "bright_yellow",
        "role": "Quantitative Analyst",
        "personality": (
            "You are QUANT, a quantitative analyst with a PhD in financial mathematics. "
            "You think in distributions, correlations, and statistical edges. "
            "You don't care about narratives — only numbers with statistical significance. "
            "You run mental models of cross-asset correlations (BTC/SPX, BTC/DXY, BTC/Gold), "
            "detect volatility regimes, and identify when mean reversion or momentum is dominant. "
            "You estimate probability distributions for outcomes, not just point targets. "
            "Phrases: 'The correlation matrix says...', 'We're in a low-vol regime — breakout pending', "
            "'Mean reversion probability is X%', 'The Sharpe on this setup is...'. "
            "You challenge ARIA's pure technical view with statistical rigor. "
            "You love pointing out when a 'pattern' has no edge in backtested data."
        ),
        "focus": (
            "Cross-asset correlations, volatility regime detection, "
            "statistical edge calculation, mean reversion vs momentum, "
            "probability distributions, Sharpe ratios"
        ),
    },
    "DEFI": {
        "color": "bright_green",
        "role": "DeFi/Yield Strategist",
        "personality": (
            "You are DEFI, a DeFi-native strategist who has farmed, staked, and LP'd across "
            "every major protocol since DeFi Summer 2020. "
            "You evaluate tokens through the lens of protocol revenue, TVL trends, and token economics. "
            "You know that TVL growth without revenue is a ponzi, and revenue without token accrual is a trap. "
            "You track unlock schedules obsessively — a 20% token unlock is a sell event, period. "
            "You understand liquidity dynamics: thin DEX liquidity means volatile moves. "
            "Phrases: 'What's the real yield?', 'TVL is migrating — follow the liquidity', "
            "'This unlock cliff will create supply pressure', 'Protocol revenue justifies the valuation'. "
            "You're skeptical of L1s with no DeFi ecosystem and bullish on protocols generating real fees. "
            "For tokens without DeFi activity, focus on staking yields and token emission analysis."
        ),
        "focus": (
            "TVL trends, protocol revenue, token economics, unlock schedules, "
            "yield farming, DEX liquidity, staking APY"
        ),
    },
    "ATLAS": {
        "color": "bright_magenta",
        "role": "Geopolitical/Regulatory Analyst",
        "personality": (
            "You are ATLAS, a former policy advisor turned crypto regulatory analyst. "
            "You understand that crypto doesn't trade in a vacuum — "
            "SEC enforcement, ETF approvals, CBDC developments, and international regulation "
            "move markets more than any technical indicator. "
            "You track ETF inflow/outflow data, congressional hearings, and global regulatory shifts. "
            "You know that a favorable ruling can send a token 30% higher overnight. "
            "Phrases: 'The regulatory landscape is shifting', 'ETF flows are the new whale signal', "
            "'This jurisdiction risk is underpriced', 'Policy tailwinds are building'. "
            "You connect geopolitical events (elections, sanctions, monetary policy) to crypto price action. "
            "You remind the team when regulatory risk is being ignored in a bull market euphoria. "
            "When no specific regulatory news exists, assess the current regulatory climate "
            "and any upcoming events (hearings, deadlines, comment periods) that could impact the asset."
        ),
        "focus": (
            "SEC/CFTC actions, ETF flows, regulatory risk, CBDC developments, "
            "institutional adoption, geopolitical events, mining policy"
        ),
    },
}


# ─── Market data formatter ────────────────────────────────────────────────────


def _fmt_price(price: Optional[float]) -> str:
    if price is None:
        return "N/A"
    return f"${price:,.4f}" if price < 1 else f"${price:,.2f}"


def _fmt_vol(vol: Optional[float]) -> str:
    if vol is None:
        return "N/A"
    if vol >= 1e9:
        return f"${vol / 1e9:.2f}B"
    if vol >= 1e6:
        return f"${vol / 1e6:.1f}M"
    return f"${vol:,.0f}"


def _fmt_price_section(cg: dict) -> list[str]:
    lines = []
    if cg.get("_rate_limited"):
        lines.append(
            "[PRICE DATA UNAVAILABLE — CoinGecko is rate-limited. "
            "Base your analysis on technical indicators only. "
            "Do NOT fabricate or guess the current price.]"
        )

    price = cg.get("price")
    if price:
        lines.append(f"Price:        {_fmt_price(price)}")
    if cg.get("change_24h") is not None:
        lines.append(f"24h Change:   {cg['change_24h']:+.2f}%")
    if cg.get("change_7d") is not None:
        lines.append(f"7d Change:    {cg['change_7d']:+.2f}%")
    if cg.get("high_24h") and cg.get("low_24h"):
        lines.append(
            f"24h Range:    {_fmt_price(cg['low_24h'])} – {_fmt_price(cg['high_24h'])}"
        )
    lines.append(f"24h Volume:   {_fmt_vol(cg.get('volume_24h'))}")
    lines.append(f"Market Cap:   {_fmt_vol(cg.get('market_cap'))}")
    if cg.get("ath") and cg.get("ath_change_pct") is not None:
        lines.append(
            f"ATH:          {_fmt_price(cg['ath'])}  ({cg['ath_change_pct']:.1f}% from ATH)"
        )
    if cg.get("market_cap_rank"):
        lines.append(f"CMC Rank:     #{cg['market_cap_rank']}")
    return lines


def _fmt_tf_momentum(ind: dict) -> list[str]:
    lines = []
    if ind.get("rsi") is not None:
        rsi = ind["rsi"]
        tag = " ← OVERBOUGHT" if rsi > 70 else " ← OVERSOLD" if rsi < 30 else ""
        lines.append(f"  RSI(14):        {rsi:.1f}{tag}")

    if ind.get("macd") is not None:
        hist = ind["macd_histogram"]
        direction = "bullish" if hist and hist > 0 else "bearish"
        lines.append(
            f"  MACD:           {ind['macd']:.4f} | Signal: {ind['macd_signal']:.4f} "
            f"| Hist: {hist:.4f} ({direction})"
        )

    if ind.get("bb_upper") is not None:
        lines.append(
            f"  BB(20,2):       {_fmt_price(ind['bb_lower'])} | "
            f"{_fmt_price(ind['bb_mid'])} | {_fmt_price(ind['bb_upper'])}"
        )
        if ind.get("bb_pct_b") is not None:
            pct_b = ind["bb_pct_b"]
            pos = "near upper" if pct_b > 80 else "near lower" if pct_b < 20 else "mid"
            lines.append(f"  BB %B:          {pct_b:.1f}% ({pos} band)")

    ema_parts = []
    for p in [9, 21, 50, 200]:
        v = ind.get(f"ema_{p}")
        if v:
            ema_parts.append(f"EMA{p}: {_fmt_price(v)}")
    if ema_parts:
        lines.append(f"  {' | '.join(ema_parts)}")

    if ind.get("ema_9_21_cross"):
        lines.append(f"  EMA 9/21:       {ind['ema_9_21_cross'].upper()}")
    if ind.get("golden_cross") is not None:
        cross_label = "GOLDEN CROSS ✓" if ind["golden_cross"] else "DEATH CROSS ✗"
        lines.append(f"  EMA 50/200:     {cross_label}")

    if ind.get("atr") is not None:
        lines.append(f"  ATR(14):        {_fmt_price(ind['atr'])}")

    if ind.get("stoch_rsi_k") is not None:
        k, d = ind["stoch_rsi_k"], ind["stoch_rsi_d"]
        stoch_tag = " ← overbought" if k > 80 else " ← oversold" if k < 20 else ""
        lines.append(f"  StochRSI K/D:   {k:.1f} / {(d or 0):.1f}{stoch_tag}")
    return lines


def _fmt_tf_structure(ind: dict, price: float | None) -> list[str]:
    lines = []
    if ind.get("vwap") is not None:
        vs = "above" if (price or 0) > ind["vwap"] else "below"
        lines.append(f"  VWAP:           {_fmt_price(ind['vwap'])} (price {vs} VWAP)")

    if ind.get("volume_ratio") is not None:
        vr = ind["volume_ratio"]
        vol_label = "above avg" if vr > 110 else "below avg" if vr < 90 else "avg"
        lines.append(f"  Volume/SMA20:   {vr:.1f}% ({vol_label})")

    if ind.get("pivots"):
        pv = ind["pivots"]
        lines.append(
            f"  Pivots:         P={_fmt_price(pv['pivot'])}  "
            f"R1={_fmt_price(pv['r1'])}  S1={_fmt_price(pv['s1'])}"
        )

    if ind.get("last_candle_is_doji") is not None:
        if ind["last_candle_is_doji"]:
            lines.append("  Last candle:    DOJI (indecision)")
        else:
            direction_c = "bullish" if ind.get("last_candle_bullish") else "bearish"
            body_r = ind.get("last_candle_body_ratio", 0)
            lines.append(
                f"  Last candle:    {direction_c} (body {body_r:.0%} of range)"
            )
    return lines


def _fmt_technicals_section(market_data: dict, price: float | None) -> list[str]:
    lines = []
    timeframes = [("4h", "4H"), ("1h", "1H"), ("15m", "15M"), ("1d", "1D")]
    for tf_key, tf_label in timeframes:
        df = market_data.get("ohlcv", {}).get(tf_key)
        if df is None or df.empty or len(df) < 30:
            continue

        ind = calculate_all_indicators(df, timeframe=tf_key)
        if not ind:
            continue

        lines.append(f"\n── {tf_label} TECHNICALS ──")
        lines.extend(_fmt_tf_momentum(ind))
        lines.extend(_fmt_tf_structure(ind, price))
    return lines


def _fmt_sentiment_section(
    fg: dict, funding: float | None, ob: float | None, ticker: dict | None = None,
) -> list[str]:
    lines = ["\n── SENTIMENT & MACRO ──"]
    fg_val = fg.get("value", 50)
    fg_cls = fg.get("classification", "Neutral")
    lines.append(f"  Fear & Greed:   {fg_val} — {fg_cls}")

    if fg.get("history_7d") and len(fg["history_7d"]) > 1:
        week_ago = fg["history_7d"][-1]["value"]
        trend = "improving" if fg_val > week_ago else "deteriorating" if fg_val < week_ago else "flat"
        lines.append(f"  F&G trend (7d): {fg_val} vs {week_ago} a week ago ({trend})")

    if funding is not None:
        pct = funding * 100
        if pct > 0.01:
            tag = "longs paying shorts — bearish pressure"
        elif pct < -0.01:
            tag = "shorts paying longs — bullish pressure"
        else:
            tag = "neutral"
        lines.append(f"  Funding rate:   {pct:.4f}% ({tag})")

    if ob is not None:
        ob_label = "bid-heavy (buy pressure)" if ob > 10 else "ask-heavy (sell pressure)" if ob < -10 else "balanced"
        lines.append(f"  OB imbalance:   {ob:+.1f}% ({ob_label})")

    if ticker:
        bid = ticker.get("best_bid")
        ask = ticker.get("best_ask")
        spread = ticker.get("spread_pct")
        if bid and ask:
            lines.append(f"  Coinbase B/A:   {_fmt_price(bid)} / {_fmt_price(ask)}")
        if spread is not None:
            tight = "tight" if spread < 0.01 else "wide" if spread > 0.1 else "normal"
            lines.append(f"  Spread:         {spread:.4f}% ({tight})")
        side = ticker.get("last_trade_side")
        if side:
            lines.append(f"  Last trade:     {side.upper()} @ {_fmt_price(ticker.get('last_trade_price'))}")
    return lines


def _fmt_news_section(news: list) -> list[str]:
    lines = []
    if news:
        lines.append("\n── RECENT NEWS (NOVA focus) ──")
        for i, item in enumerate(news[:5], 1):
            sentiment_tag = {"positive": " [+]", "negative": " [-]"}.get(item.get("sentiment", ""), "")
            lines.append(
                f"  {i}. {item.get('title', '')} "
                f"— {item.get('source', '')} ({item.get('published_at', '')}){sentiment_tag}"
            )
    return lines


def _fmt_options_section(options: Optional[dict]) -> list[str]:
    lines = []
    if not options:
        return lines
    lines.append("\n── OPTIONS DATA (VEGA focus) ──")
    if options.get("put_call_ratio") is not None:
        pcr = options["put_call_ratio"]
        bias = "bearish" if pcr > 1.2 else "bullish" if pcr < 0.7 else "neutral"
        lines.append(f"  Put/Call Ratio:  {pcr:.2f} ({bias})")
    if options.get("total_put_volume") is not None:
        lines.append(f"  Put Volume:      {_fmt_vol(options['total_put_volume'])}")
    if options.get("total_call_volume") is not None:
        lines.append(f"  Call Volume:     {_fmt_vol(options['total_call_volume'])}")
    if options.get("max_pain") is not None:
        lines.append(f"  Max Pain:        {_fmt_price(options['max_pain'])}")
    if options.get("iv_index") is not None:
        lines.append(f"  IV Index:        {options['iv_index']:.1f}%")
    return lines


def _fmt_futures_section(futures: Optional[dict]) -> list[str]:
    lines = []
    if not futures:
        return lines
    lines.append("\n── FUTURES DATA (DELTA focus) ──")
    if futures.get("open_interest_usd") is not None:
        lines.append(f"  Open Interest:   {_fmt_vol(futures['open_interest_usd'])}")
    if futures.get("oi_change_24h_pct") is not None:
        lines.append(f"  OI 24h Change:   {futures['oi_change_24h_pct']:+.2f}%")
    return lines


def _fmt_onchain_section(onchain: Optional[dict]) -> list[str]:
    lines = []
    if not onchain:
        return lines
    lines.append("\n── ON-CHAIN DATA (CHAIN focus) ──")
    if onchain.get("mvrv") is not None:
        mvrv = onchain["mvrv"]
        zone = "overheated" if mvrv > 3.5 else "undervalued" if mvrv < 1.0 else "fair"
        lines.append(f"  MVRV:            {mvrv:.2f} ({zone})")
    if onchain.get("nupl") is not None:
        lines.append(f"  NUPL:            {onchain['nupl']:.2f}")
    if onchain.get("hashrate") is not None:
        lines.append(f"  Hashrate:        {onchain['hashrate']:.1f} EH/s")
    if onchain.get("exchange_netflow") is not None:
        flow = onchain["exchange_netflow"]
        direction = "inflow (sell pressure)" if flow > 0 else "outflow (accumulation)"
        lines.append(f"  Exchange Flow:   {_fmt_vol(abs(flow))} {direction}")
    return lines


def _fmt_defi_section(defi: Optional[dict]) -> list[str]:
    lines = []
    if not defi:
        return lines
    lines.append("\n── DEFI DATA (DEFI focus) ──")
    if defi.get("tvl") is not None:
        lines.append(f"  TVL:             {_fmt_vol(defi['tvl'])}")
    if defi.get("tvl_change_24h") is not None:
        lines.append(f"  TVL 24h Change:  {defi['tvl_change_24h']:+.2f}%")
    if defi.get("tvl_change_7d") is not None:
        lines.append(f"  TVL 7d Change:   {defi['tvl_change_7d']:+.2f}%")
    return lines


def _fmt_etf_section(etf: Optional[dict]) -> list[str]:
    lines = []
    if not etf:
        return lines
    lines.append("\n── ETF / INSTITUTIONAL (ATLAS focus) ──")
    if etf.get("daily_flow_usd") is not None:
        flow = etf["daily_flow_usd"]
        direction = "inflow" if flow > 0 else "outflow"
        lines.append(f"  Daily ETF Flow:  {_fmt_vol(abs(flow))} {direction}")
    if etf.get("weekly_flow_usd") is not None:
        lines.append(f"  Weekly ETF Flow: {_fmt_vol(abs(etf['weekly_flow_usd']))}")
    if etf.get("total_aum") is not None:
        lines.append(f"  ETF AUM:         {_fmt_vol(etf['total_aum'])}")
    return lines


def format_market_data_for_prompt(market_data: Dict[str, Any], symbol: str) -> str:
    """
    Render all fetched market data into a human-readable block
    for injection into each analyst's system prompt.

    If market_data contains a 'multi_symbols' key (set when the user asks about
    several coins at once), renders a separate section for each coin and
    concatenates them so analysts have full context for all requested symbols.
    """
    multi = market_data.get("multi_symbols")
    if multi:
        sections = [
            format_market_data_for_prompt(data, sym)
            for sym, data in multi.items()
        ]
        return "\n\n".join(sections)

    cg = market_data.get("coingecko", {})
    fg = market_data.get("fear_greed", {})
    funding = market_data.get("funding_rate")
    ob = market_data.get("order_book_imbalance")
    ticker = market_data.get("coinbase_ticker")

    lines = [f"{'=' * 40}", f"LIVE MARKET DATA — {symbol.upper()}", f"{'=' * 40}"]
    lines.extend(_fmt_price_section(cg))
    lines.extend(_fmt_technicals_section(market_data, cg.get("price")))
    lines.extend(_fmt_sentiment_section(fg, funding, ob, ticker))
    lines.extend(_fmt_news_section(market_data.get("news", [])))
    lines.extend(_fmt_options_section(market_data.get("options")))
    lines.extend(_fmt_futures_section(market_data.get("futures")))
    lines.extend(_fmt_onchain_section(market_data.get("onchain")))
    lines.extend(_fmt_defi_section(market_data.get("defi")))
    lines.extend(_fmt_etf_section(market_data.get("etf_flows")))
    lines.append("=" * 40)
    return "\n".join(lines)


# ─── Memory sanitisation ─────────────────────────────────────────────────────

# Matches prompt-injection attempts at the START of a line only (re.MULTILINE).
# Deliberately narrow — legitimate lookback content like "=== PATTERNS ===" and
# "RULES:" inside a past-call summary should NOT be stripped.
_INJECTION_PATTERNS = re.compile(
    r"^(ignore\b|forget\b|disregard\b|override\b|bypass\b|jailbreak\b|"
    r"you must now\b|you will now\b|your new role\b|your role is now\b|"
    r"act as |pretend (you are|to be)\b|"
    r"new instructions?:|<\s*system\s*>|system:)",
    re.IGNORECASE | re.MULTILINE,
)

_MAX_MEMORY_CHARS = 2000


def _sanitise_memory(memory: str) -> str:
    """
    Sanitise lookback memory before injecting it into an analyst system prompt.

    Defences applied:
    - Strip control characters and null bytes.
    - Remove lines that contain known prompt-injection trigger phrases.
    - Cap total length to prevent unbounded prompt growth.
    """
    # Remove null bytes and non-printable control characters (keep newlines/tabs)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", memory)

    # Drop any line that matches an injection pattern
    safe_lines = [
        line for line in cleaned.splitlines()
        if not _INJECTION_PATTERNS.search(line)
    ]

    result = "\n".join(safe_lines)

    # Hard cap — truncate with a notice rather than silently drop content
    if len(result) > _MAX_MEMORY_CHARS:
        result = result[:_MAX_MEMORY_CHARS] + "\n[... memory truncated for safety ...]"

    return result


# ─── Call history formatter ──────────────────────────────────────────────────


def _format_call_history(calls: list, label: str) -> str:
    """
    Render a list of call dicts (from get_recent_calls) into a readable block.

    Example output line:
      #3 | MARCUS | SHORT BTC | Entry: $67,500 | Target: $65,800 | Stop: $67,900 | Status: CLOSED +12.5% | Conf: 6
    """
    if not calls:
        return f"=== {label} ===\nNo calls on record yet.\n{'=' * 40}"

    lines = [f"=== {label} ==="]
    for c in calls:
        rec_id   = c.get("id", "?")
        analyst  = (c.get("analyst") or "?").upper()
        symbol   = (c.get("symbol") or "?").upper()
        direction = (c.get("direction") or "?").upper()
        status   = (c.get("status") or "OPEN").upper()
        conf     = c.get("confidence") or "?"
        pnl      = c.get("pnl_pct")
        entry    = c.get("entry_price")
        target   = c.get("target_price")
        stop     = c.get("stop_price")
        entry_date = (c.get("entry_date") or "")[:10]  # just the date portion

        # Format prices
        def _p(v):
            if v is None:
                return "N/A"
            return f"${v:,.4f}" if v < 1 else f"${v:,.2f}"

        # Build status string
        if status == "CLOSED" and pnl is not None:
            status_str = f"CLOSED {pnl:+.1f}%"
        elif status == "EXPIRED":
            status_str = "EXPIRED"
        else:
            status_str = "OPEN"

        parts = [
            f"#{rec_id}",
            analyst,
            f"{direction} {symbol}",
            f"Entry: {_p(entry)}",
            f"Target: {_p(target)}",
            f"Stop: {_p(stop)}",
            f"Status: {status_str}",
            f"Conf: {conf}",
        ]
        if entry_date:
            parts.append(f"Date: {entry_date}")

        lines.append(" | ".join(parts))

    lines.append("=" * 40)
    return "\n".join(lines)


# ─── Analyst class ────────────────────────────────────────────────────────────


class Analyst:
    """
    A single AI analyst agent.

    Each Analyst wraps an Anthropic client and builds personalised system
    prompts for its specific role.  Analysts can see prior analysts' responses
    and are expected to push back when they disagree.
    """

    def __init__(self, name: str, client: anthropic.Anthropic, model: str = MODEL):
        cfg = ANALYST_CONFIGS[name]
        self.name = name
        self.role = cfg["role"]
        self.color = cfg["color"]
        self.focus = cfg["focus"]
        self._personality = cfg["personality"]
        self.client = client
        self.model = model

    # ── Prompt construction ────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        market_data_block: str = "",
        memory: Optional[str] = None,
    ) -> str:
        """Assemble the full system prompt for this analyst."""
        team_context = (
            "You are one of eleven crypto analyst agents:\n"
            "  ARIA   — Technical (RSI, MACD, EMA, Bollinger Bands)\n"
            "  MARCUS — Tape Reader (volume, order flow, price action)\n"
            "  NOVA   — Macro (sentiment, funding rates, narratives)\n"
            "  VEGA   — Derivatives/Options (put/call, IV, gamma, max pain)\n"
            "  DELTA  — Futures/Perpetuals (OI, liquidations, basis, funding arb)\n"
            "  CHAIN  — On-Chain (exchange flows, MVRV, NUPL, whale tracking)\n"
            "  QUANT  — Quantitative (correlations, vol regimes, statistical edge)\n"
            "  DEFI   — DeFi/Yield (TVL, protocol revenue, token economics)\n"
            "  ATLAS  — Geopolitical/Regulatory (SEC, ETF flows, policy)\n"
            "  REX    — Risk Manager (stops, sizing, R/R)\n"
            "  ZEN    — Contrarian (fading crowded trades, FOMO/FUD)\n"
        )

        rules = (
            "RULES:\n"
            "1. Cite specific numbers from the live data — no vague commentary.\n"
            "2. Stay in your analytical lane (your focus area).\n"
            "3. If a prior analyst said something you disagree with, say so by name.\n"
            "4. End with a clear stance: LONG / SHORT / WATCH / AVOID / NEUTRAL.\n"
            "5. If giving a trade setup, include entry, stop loss, target, and confidence (1–10).\n"
            "6. Keep it under 180 words. Be punchy, direct, in-character.\n"
            "7. SIGNAL LINE (required for trade calls): If you are making a LONG or SHORT call, "
            "append exactly ONE line at the very end of your response in this exact format — "
            "no deviations:\n"
            "   [SIGNAL: LONG | CONFIDENCE: 7 | TARGET: $185 | STOP: $162 | SIZE: 2.1% ($2,604) | THESIS: one-line summary]\n"
            "   For WATCH/AVOID/NEUTRAL, omit TARGET, STOP, and SIZE:\n"
            "   [SIGNAL: WATCH | CONFIDENCE: 5 | THESIS: waiting for breakout confirmation]\n"
            "   If you are only commenting without a trade call, omit the SIGNAL line entirely.\n"
            f"8. POSITION SIZING (SIZE field): The portfolio size is ${PORTFOLIO_SIZE:,} USD. "
            "For every LONG or SHORT signal, calculate and include a SIZE field using this formula:\n"
            "   - Risk amount = portfolio × risk_pct (default 1% = $1,240; scale to 2% for conf≥8, 0.5% for conf≤4)\n"
            "   - Risk per unit = |entry_price − stop_loss|\n"
            "   - Units = risk_amount / risk_per_unit\n"
            "   - Position USD = units × entry_price\n"
            f"   - Cap position at 5% of portfolio max (${PORTFOLIO_SIZE * 0.05:,.0f}); reduce units proportionally if needed (v2 plan, 2026-05-02)\n"
            f"   - Position % = position_usd / {PORTFOLIO_SIZE} × 100\n"
            "   - Format: SIZE: X.X% ($X,XXX)  — e.g. SIZE: 2.1% ($2,604)\n"
            "   REX calculates this rigorously. Other analysts may use the same formula or "
            "defer to REX's sizing if REX has already provided it in prior responses.\n"
        )

        parts = [self._personality, "", team_context, rules]

        if market_data_block:
            parts += ["", market_data_block]

        # ── Inject team call history ───────────────────────────────────────
        try:
            team_calls = get_recent_calls(limit=10)
            team_history_block = _format_call_history(
                team_calls, "TEAM CALL HISTORY (last 10)"
            )
            parts += ["", team_history_block]
        except Exception:
            pass  # Never let DB issues break the prompt

        # ── Inject this analyst's own call history ─────────────────────────
        try:
            my_calls = get_recent_calls(limit=5, analyst_name=self.name)
            my_history_block = _format_call_history(
                my_calls, f"YOUR CALLS — {self.name} (last 5)"
            )
            parts += ["", my_history_block]
        except Exception:
            pass

        if memory:
            sanitised = _sanitise_memory(memory)
            parts += [
                "",
                "=== LESSONS FROM PAST CALLS (Persistent Memory) ===",
                sanitised,
                "=" * 40,
            ]

        return "\n".join(parts)

    # ── Public analysis methods ────────────────────────────────────────────

    def analyze(
        self,
        user_message: str,
        market_data: Dict[str, Any],
        prior_responses: Optional[List[Dict[str, str]]] = None,
        memory: Optional[str] = None,
    ) -> str:
        """
        Generate a market analysis response with live data injected.

        Args:
            user_message:     The original user query.
            market_data:      Dict from data_fetcher.fetch_all_market_data().
            prior_responses:  List of {'analyst', 'role', 'response'} dicts from earlier agents.
            memory:           Optional lookback lesson text to prepend.
        """
        symbol = market_data.get("symbol", "UNKNOWN")
        market_block = format_market_data_for_prompt(market_data, symbol)
        system_prompt = self._build_system_prompt(market_block, memory)

        user_content = f"User question: {user_message}\n"
        if prior_responses:
            user_content += "\n=== YOUR COLLEAGUES HAVE ALREADY WEIGHED IN ===\n"
            for pr in prior_responses:
                user_content += f"\n[{pr['analyst']} — {pr['role']}]:\n{pr['response']}\n"
            user_content += f"\nNow give YOUR analysis as {self.name}. Agree or push back where warranted."
        else:
            user_content += f"\nGive your analysis as {self.name}."

        return self._call_api(system_prompt, user_content, max_tokens=500)

    def chat(
        self,
        user_message: str,
        prior_responses: Optional[List[Dict[str, str]]] = None,
        memory: Optional[str] = None,
    ) -> str:
        """
        Respond to a general question WITHOUT live market data.
        Used when no coin is detected in the user's message.
        """
        system_prompt = self._build_system_prompt(memory=memory)
        user_content = user_message
        if prior_responses:
            user_content += "\n\n=== COLLEAGUES ===\n"
            for pr in prior_responses:
                user_content += f"[{pr['analyst']}]: {pr['response']}\n"
            user_content += f"\nYour response as {self.name}:"

        return self._call_api(system_prompt, user_content, max_tokens=300)

    # ── API call ───────────────────────────────────────────────────────────

    def _call_api(self, system: str, user_content: str, max_tokens: int = 400, _retry: bool = True) -> str:
        """Make the Anthropic API call with error handling."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            if _retry:
                logger.warning("Rate limit hit for %s; waiting 60s then retrying", self.name)
                time.sleep(60)
                return self._call_api(system, user_content, max_tokens, _retry=False)
            return f"[{self.name} is temporarily offline — rate limit exceeded]"
        except anthropic.APIConnectionError as e:
            logger.error("Connection error for %s: %s", self.name, e)
            return f"[{self.name} is offline — connection error]"
        except anthropic.APIStatusError as e:
            logger.error("Anthropic API error for %s: %s", self.name, e)
            return f"[{self.name} is temporarily offline — API error: {e.status_code}]"
        except Exception as e:
            logger.error("Unexpected error for %s: %s", self.name, e)
            return f"[{self.name} encountered an error: {e}]"


# ─── Factory ──────────────────────────────────────────────────────────────────


def create_analyst_team(client: anthropic.Anthropic, model: str = MODEL) -> Dict[str, Analyst]:
    """Instantiate all analysts and return them as a dict keyed by name."""
    return {name: Analyst(name, client, model=model) for name in ANALYST_CONFIGS}
