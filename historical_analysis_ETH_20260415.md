# ETH — Weekly Lookback (7 days)

_Generated 2026-04-15T13:21:30+00:00 UTC (Cowork fallback run)_

---

**KEY PATTERNS** — What conditions or signals correlated with accurate calls?

The 7d window has 69 ETH rows (58 LONG / 11 SHORT), with 10 closed — but only 2 winners. The winners were CHAIN (+8.8%) and ZEN (+7.0%), both LONG at 2026-04-13T22:54 when 7 OTHER analysts were SHORT into the same minute. Their shared ingredient was ETH/BTC relative strength at multi-month lows interpreted as a mean-reversion or crowded-short fade. Everyone who sided with the aggregate "weak tape" thesis (MARCUS ×4, VEGA, DELTA, QUANT, REX) lost between -0.4% and -2.5%. The clear pattern: *when the consensus is SHORT on ETH while the relative-strength signal (ETH/BTC) is already at an extreme, the contrarian LONG is the profitable side*. Post-pivot (2026-04-14 onward), the team correctly rotated LONG after NOVA flagged "ETH leading BTC on 24h" — but by then ETH had already moved ~5% of the available edge.

**FAILURES** — Where did analysts get it wrong and what did they miss?

Eight distinct SHORT calls on 2026-04-13 closed red, led by MARCUS (4 losing SHORTs in 7 hours). MARCUS's repeated "distribution at resistance" read was pattern-matching on 1H tape without checking the ETH/BTC context CHAIN and ZEN picked up. The failure was time-frame mismatch: MARCUS's 1H tape was bearish while the daily structure was carving a higher low. Once the team flipped LONG on 2026-04-14T12:04, 9 analysts piled in at ~$2,370 with targets $2,500–$2,800; by 2026-04-15T12:59 price is still pressing range-high and confidence had faded from 7s to 4–5s — i.e., the team bought the breakout and then lost faith at the retest, which is the exact emotional curve you want to avoid in a trend trade.

**POSITION SIZING & CORRELATION** — At 2026-04-13T22:54, 7 analysts went SHORT ETH in the same minute (MARCUS/VEGA/DELTA/QUANT/REX + NOVA-adjacent theses) — that's not 7 independent signals, it's one book short packaged as a committee. Combined notional ~$11.1K at ~1.4:1 ratio against the 2 correlated LONGs (CHAIN + ZEN, ~$3.1K). Net book was ~-$8K short ETH just as the move reversed. At 2026-04-14T12:04, 10 analysts went LONG ETH in the same minute (no dissenters) — the full inverse correlated-book position, ~$24K notional (~19% of a $124K book). REX was SHORT on 2026-04-13 and LONG on every subsequent run, again trading his own consensus rather than adjudicating it. ZEN's SHORT calls at 22:44 and 00:38 are the only genuine L/S offsets in the later rounds.

**LESSONS LEARNED**

1. Require an ETH/BTC relative-strength check before any directional ETH call — when ETH/BTC is at a 60d extreme, force the default stance to WATCH unless an analyst explicitly justifies trading against mean reversion.
2. MARCUS must not re-enter a losing SHORT thesis more than twice in 12 hours with the same invalidation. Hard-code "no triple-try" in the tape-reader prompt.
3. When ≥7 analysts align in the same direction in the same minute, halve the per-analyst size so aggregate book risk stays under 10% of NAV — the 2026-04-14 LONG round was a ~19% gross ETH bet dressed as 10 independent 2% opinions.
4. Trend-continuation calls (like 2026-04-14 LONG) should lock a minimum hold horizon; the team's confidence eroding from 7→4 across 3 days on an unchanged setup is evidence of recency bias, not new information.
5. VEGA repeatedly calls "gamma pulls to $2,400" regardless of whether price is above or below — persona needs clearer distinction between pin risk above vs below the dealer wall.

**BIAS WATCH** — Ordering bias produced the 2026-04-13 SHORT cascade: MARCUS shorts on tape, then VEGA/DELTA/QUANT/REX all SHORT citing "team alignment" or beta-drag — none re-derived from first principles. CHAIN and ZEN, running later in order, broke the chain precisely because their mandates (on-chain + contrarian) force a different data source. Anchoring is clear in VEGA's repeated $2,400 gamma line. Groupthink on 2026-04-14 LONG was worse — 10 unanimous LONGs is the team functioning as one agent. ZEN failed the contrarian mandate on the 22:54 LONG (went with crowd contrarian, which is still crowd) but partially recovered with SHORTs at 22:44 and 00:38. Action: block analyst N from referencing analyst N-1's directional conclusion for the first paragraph of analysis; force independent data-pull first.
