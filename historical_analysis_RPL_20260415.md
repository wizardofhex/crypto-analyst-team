# RPL — Weekly Lookback (7 days)

_Generated 2026-04-15T13:21:30+00:00 UTC (Cowork fallback run)_

---

**KEY PATTERNS** — What conditions or signals correlated with accurate calls?

32 RPL rows in the 7d window (31 LONG / 1 SHORT) and **zero closed trades** — so no outcome-based verdict is possible yet. The directional read is near-unanimous LONG based on four repeating theses: (1) token price disconnected from stable validator share / TVL (CHAIN, DEFI), (2) high-beta ETH-proxy on an ETH up-move (NOVA, QUANT), (3) -97% drawdown from ATH = asymmetric contrarian lottery (ZEN, REX small-size), and (4) thin liquidity forcing discipline rather than opportunity (REX, ARIA). Targets cluster $1.90–$2.20 against stops $1.65–$1.73 — R:R ~1.3–1.7:1, which is modest for a small-cap with this level of drawdown. The single dissent was DEFI on 2026-04-14T22:44 (SHORT, "market share bleed to Lido plus inflation tokenomics") — notable because DEFI had been LONG 5 hours earlier and LONG 2 hours later, so the SHORT is essentially a one-off inflation-warning flag, not a regime call.

**FAILURES** — No closes = no realized losses, but the process-level failure is that RPL has become a default "small LONG" across the team regardless of the setup. Sizes drifted UP from the 2026-04-13 start (0.5% max, matching REX's illiquidity prescription) to 2026-04-14T22:44 rounds at 1.0% for most analysts — i.e., as price moved, the team grew more aggressive in a name whose thin-liquidity constraint hasn't changed. By 2026-04-15T12:59 sizes correctly compressed back to 0.3–0.5%, but the intervening 2 days of 1.0% exposure in a -97%-drawdown illiquid altcoin is the kind of sizing creep that turns a "lottery ticket" into a real drawdown vector.

**POSITION SIZING & CORRELATION** — Several rounds had 4–6 concurrent LONGs in the same minute (2026-04-13T22:54: CHAIN/DEFI/REX/ZEN; 2026-04-14T12:04: 6 analysts; 2026-04-14T16:35: 6 analysts; 2026-04-14T22:44: 4 LONG vs 1 DEFI SHORT). Peak aggregate sizing at 12:04 was ~5.0% of NAV in RPL (six analysts at ~0.5–1.0% each) — for a small-cap with -97% drawdown that's meaningful concentration. More importantly, RPL longs are NOT independent of ETH longs: the thesis is literally "ETH beta." So whenever the team is simultaneously LONG BTC, LONG ETH, and LONG RPL (as on 2026-04-14T12:04, 16:35, 22:44, 00:38), the aggregate correlated book is ~25–30% of NAV pointing one way. REX did correctly flag "thin liquidity demands tiny size" repeatedly but didn't veto other analysts' creeping sizes. The single DEFI SHORT creates a token L/S, but the rest of DEFI's week was LONG — so the SHORT is isolated.

**LESSONS LEARNED**

1. Max 0.5% per-analyst, ≤1.5% aggregate book limit on RPL (or any coin below $200M daily volume). Hard-code this in REX's prompt — the 2026-04-14T22:44 round with 4 analysts at 1.0% each (aggregate 4%) violated sensible small-cap sizing.
2. RPL calls must explicitly quote the ETH correlation assumption and subtract that exposure from the standalone thesis. If the only reason is "ETH beta," do not open a new line — it's a duplicate of the ETH long.
3. DEFI's inflation/unlock warning on 2026-04-14T22:44 was the single best challenger to consensus — future RPL rounds should default to WATCH unless at least one analyst addresses the inflation-schedule counter-argument.
4. A name at -97% from ATH should carry a minimum 2:1 R:R bar, not the 1.3–1.7:1 typical of this week's setups. Tighten target discipline.
5. Stop clustering at $1.65–$1.73 is a liquidity trap: a single stop-run wick takes out the entire team simultaneously. Stagger stops or use staggered entries to avoid single-point-of-failure risk.

**BIAS WATCH** — Classic small-cap "lottery ticket" bias: every analyst frames the -97% drawdown as asymmetric upside without owning the symmetric downside (RPL could go to $1). Anchoring on the ATH-distance ("-97%") as if further drawdown is bounded. Ordering bias is strong — ZEN, running last, repeats the contrarian framing four times with nearly identical language ("maximum pessimism," "crowded short fade," "washed-out small cap"), which suggests the persona has memorized the outcome rather than re-derived it. The near-absence of SHORT or WATCH entries is the loudest signal: 31 LONG vs 1 SHORT on a coin with zero closed trades means the team has no discriminator yet and is defaulting to "cheap = long." Action: require every RPL round to have at least one analyst propose WATCH with a specific trigger ($1.83 close, or volume expansion ≥2x) before any LONG size above 0.5% is allowed.
