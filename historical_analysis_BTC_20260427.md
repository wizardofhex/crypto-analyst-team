# BTC — Weekly Lookback (7 days)

_Generated 2026-04-27T03:40:11+00:00 UTC (Cowork fallback run)_

---

**KEY PATTERNS** — What conditions or signals correlated with accurate calls?

The BTC week was dominated by one trade: the 4/20 capitulation-bounce LONG. Every BB-lower bounce signal — oversold StochRSI, zero/negative funding after a flush, F&G reading of "Fear" (29–32), elevated put skew — fired in unison and the trade worked exactly as drawn for ~36 hours, generating +1.7% to +5.0% closed wins across 23 of 25 resolved positions (92% hit rate). The replicating signature: BB%B in the lower decile, funding reset to ≈0 or negative, and no scheduled regulatory catalyst. ARIA, MARCUS, DELTA and QUANT in confluence at the BB-lower with funding-reset was the cleanest edge of the week. Confidence-6 LONGs from the cohort are running at near-100% win rate, validating the calibration of the 4/20 lookback rule.

**FAILURES** — Where did analysts get it wrong and what did they miss?

The two losing closed BTC positions were both at the 4/23 16:39 cohort (ARIA -1.2%, MARCUS -0.9%) — small losses, but they highlight the failure mode: chasing continuation LONGs at pivot resistance after the easy bounce was already paid. Both theses cited "absorption doji" / "bullish stack" but the position was opened into stalling momentum and stopped on the very next 4h candle. Nobody priced the diminishing R:R as price approached prior resistance; the team kept feeding LONGs into a maturing move instead of taking partial risk off.

**POSITION SIZING & CORRELATION** — 

Three glaring correlated-book windows this week:
- **4/20 04:37 — 8 analysts LONG BTC in one hour** (MARCUS, NOVA, VEGA, DELTA, QUANT, ATLAS, REX, ZEN). The trade worked, but a 4-of-4 cohort win does not retroactively make 8 simultaneous LONGs "8 independent calls" — it was one trade replicated 8 times.
- **4/20 08:38 — 9 analysts LONG BTC** (ARIA added). Same trade, slightly later, same direction.
- **4/20 16:26 — 6 analysts LONG BTC**. Third stacking event in 12 hours.

REX is **trading his own book** — the 4/24 04:42 and 4/24 20:42 SHORT entries are explicitly flagged as "book-hedge against 114% LONG exposure" rather than directional calls. That's a legitimate risk-manager action, but it muddies the analyst track-record signal: REX's SHORTs are not directional opinions and should be tagged as `book_hedge` so they're excluded from win-rate calibration.

ZEN failed the contrarian mandate on BTC three times in 12 hours (4/20 04:37, 08:38, 16:26 — joined the LONG cohort each time). The "Fear ≠ crowded" rationalization is plausible once; three iterations is groupthink with a contrarian costume. The HARD CAP that kicked in on 4/22 ($620 floor sizing) is doing the right thing — it's mechanically capping the correlated-book risk that the team isn't capping itself.

**LESSONS LEARNED**

1. When 6+ analysts independently arrive at LONG BTC at the BB-lower with zero funding, the second and third cohort-replications add no new information — REX should explicitly downsize replicated cohorts after the first, not just apply per-trade R:R.
2. ZEN must enforce a hard rule: **if 5+ analysts agree on direction within the same hour, ZEN takes the opposite side at minimum size, period.** "Fear ≠ crowded" is not a contrarian mandate.
3. Continuation LONGs at pivot resistance after the easy bounce (4/23 16:39 setup) need a structural rule — no fresh LONG within 1.5% of recent R1 unless volume confirms the break first.
4. REX's book-hedge SHORTs need a `book_hedge` tag so they don't pollute his directional track record — currently his conf=6 win rate cited in his own theses includes both his LONG calls and his hedges, which is double-counting.
5. The HARD CAP is the only thing that prevented this week from being a 9-on-1 directional bet — keep it active until demonstrated cohort-divergence returns.

**BIAS WATCH**

Severe **ordering bias** in the 4/20 cohort runs: ARIA leads with the bounce thesis, every subsequent analyst rationalizes the same trade with their domain-specific framing rather than producing an independent read. NOVA's "F&G Fear = contrarian setup" is the same idea as ZEN's "consensus-long because Fear ≠ crowded" is the same idea as REX's "2.8:1 R:R with tight stop" — three different vocabularies for one trade. **Anchoring on the F&G reading** is the dominant systematic bias: F&G of 29–32 was treated as a buy signal in 11 separate analyst calls without anyone questioning whether F&G has any forward edge in a low-vol regime. ZEN's contrarian failure is the loudest pattern of the week.

