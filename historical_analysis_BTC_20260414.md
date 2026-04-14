# BTC — Weekly Lookback (7 days)

_Generated 2026-04-14T11:52:58Z UTC (Cowork fallback run)_

---

**KEY PATTERNS** — BTC team converged on contrarian-long setups at range lows. Apr 7 calls (ARIA, NOVA) at $68,476 triggered on StochRSI 1.2 capitulation + Extreme Fear 11 — textbook oversold bounce framing. The Apr 13 round at ~$71,200 repeats that playbook: MACD bullish cross + coiled range, 70K liquidation-cluster floor, and multi-week fear streak interpreted as contrarian fuel. Consistent confluence indicator: technical exhaustion (StochRSI/RSI) + sentiment extreme (Fear & Greed) + on-chain whale accumulation signals a bounce setup the team reliably identifies.

**FAILURES** — Both Apr 7 closed calls lost -0.04% (essentially stopped for zero gain). Data-entry issue flagged: target $2,165 and stop $2,050 on a $68K BTC trade are obviously wrong (ETH-scale prices) — suggests the signal-generation prompt or parser is leaking cross-symbol values. Analysts did not self-correct invalid R:R ratios before persisting. The bounce thesis was directionally fine but stops/targets never reflected actual volatility.

**POSITION SIZING & CORRELATION** — CRITICAL: 7 of 11 analysts (ARIA, NOVA, DELTA, CHAIN, QUANT, REX, ZEN) went LONG BTC in the same 22:54 UTC window on Apr 13 at the same ~$71,200 entry with nearly identical stops (69,500–70,000). Zero dissent — no SHORT, no WATCH. This is textbook correlated-book risk: if range breaks down, the whole team takes a simultaneous loss. REX approving the stack while being one of the 7 longs means the risk manager validated his own trade. Confidence scores clustered 5–7, no outlier.

**LESSONS LEARNED**
- Sanity-check stop/target against entry price before persisting — reject any trade where (stop/entry) is outside [0.85, 1.15] for BTC.
- When 5+ analysts converge LONG/SHORT the same coin, force at least one dissenting review (route to ZEN with contrarian mandate, not just confirmation).
- On BTC bounce setups, widen stops beyond the obvious liq cluster — stops at round-number "floors" (70K) are exactly where they get swept.
- The "extreme fear streak → contrarian long" pattern works directionally but needs tighter trade management; recent outcome shows exits near entry, not at target.
- Track whether REX's R:R math uses the correct symbol's price — add a unit-test for entry/target/stop scale consistency.

**BIAS WATCH** — Severe directional herding: the team has an anchoring bias toward "fear = buy" and keeps stacking longs without a short-side red-team. Confirmation bias is compounded by ordering — later analysts (REX, ZEN) see the prior stack of longs and rationalize agreement. ZEN is failing its contrarian mandate by joining the crowd. Guard against: (1) treating sentiment extremes as automatic entries, (2) copy-paste stop placements at obvious liq clusters, (3) risk manager greenlighting positions he personally holds.
