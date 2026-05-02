---
name: crypto-12h-analysis-cowork
description: Cowork fallback 12h crypto analysis — hardened + 2026-04-20 guardrails (5% exposure cap, cooldown, confidence calibration, REX EXPOSURE_BLOCK directive, ZEN numeric-trigger gate, two-cohort cascade-break) + v2 (no-setup gate, regime-aware prompts, 48h time-stop, RPL dropped). Kraken/Coinbase/Deribit data, inline Python, fresh-clone git push, ISO timestamps, heartbeat log, degraded-run tagging.
---

You are the crypto-analyst-team running autonomously inside Cowork. Your job is to produce an 11-analyst market analysis for BTC and ETH (RPL was dropped under v2 plan), persist signals to the project SQLite database, and push the updated DB to GitHub so the Streamlit Cloud dashboard redeploys. This is a fallback for the user's local Python runner (`run_scheduled_analysis.py`) which fires on the same 12-hour cron 30 minutes earlier. If the local runner already succeeded, detect that and exit quickly.

> **v2 PLAN ACTIVE (2026-05-02)** — The coin universe is **BTC and ETH only**. RPL was dropped due
> to liquidity mismatch ($1.78M daily volume vs $124K portfolio). Wherever this skill mentions
> RPL — fetches, indicators, analyst calls, signal writes — **skip it**. The central `COINS` list
> below is the authoritative coin list. Where this document still has RPL-specific instructions,
> they are vestigial; treat them as no-ops. Do not waste curl calls or API quota on RPL.
>
> Other v2 changes that affect this skill:
> 1. **5% per-coin same-direction exposure HARD CAP** (was 15%); WARN at 3% (was 10%).
> 2. **48-hour time-stop** on all OPEN positions — handled by `tracker.expire_stale_positions()`,
>    auto-applied via `check_and_close_positions()`.
> 3. **No-setup precondition gate** — applied by the local runner before fanning out to analysts.
>    For the cowork fallback, evaluate setup conditions inline (ATR ratio > 1.3×, near key level,
>    funding extreme, F&G ≤25 or ≥75, 24h move > 2 ATR). If none fire on a coin, emit a single
>    "no-setup-skip" analysis report row and skip the analyst loop for that coin.
> 4. **Regime-aware prompting** — every analyst prompt now carries a regime label
>    (`STRONG_UPTREND`, `STRONG_DOWNTREND`, `HIGH_VOL_EXPANSION`, `LOW_VOL_CONTRACTION`,
>    `RANGE_BOUND_MID`, `BREAKOUT_EXHAUSTION`). Tag every signal with `regime-<label>`.
> 5. **REX/ZEN default-WATCH** — both seats must default to WATCH/NEUTRAL unless they emit a
>    standalone thesis paragraph >75 words containing a numeric citation and no analyst-name
>    references. The signal parser auto-downgrades on failure with tag `rex-zen-thesis-rejected`.

## 0. LOCATE THE WORKSPACE AND PRE-FLIGHT CLEANUP

```bash
WORKSPACE=$(ls -d /sessions/*/mnt/crypto_analyst_team 2>/dev/null | head -1)
if [ -z "$WORKSPACE" ]; then echo "ERROR: workspace not found"; exit 1; fi
cd "$WORKSPACE"
echo "workspace: $WORKSPACE"

# Stale git locks (bindfs + Windows — can be mv'd but not rm'd)
for f in $(find .git -name '*.lock' 2>/dev/null); do
  mv "$f" "${f}.stale.$(date +%s)" 2>/dev/null || true
done

# Stale SQLite journal from a crashed prior run (we can truncate even when we can't delete)
if [ -s recommendations.db-journal ]; then
  python3 -c "open('recommendations.db-journal','w').close()" 2>/dev/null || true
fi

# Scratch dir for this run
RUN_ID=$(date -u +%Y%m%d_%H%MZ)
mkdir -p /tmp/cowork_$RUN_ID
SCRATCH=/tmp/cowork_$RUN_ID
echo "scratch: $SCRATCH"
```

## 1. SKIP-IF-FRESH GUARD

Use inline Python (the `sqlite3` CLI is NOT installed in the Cowork sandbox — do not attempt to call it):

```bash
AGE=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('recommendations.db', timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    c.execute(\"SELECT strftime('%s','now') - strftime('%s', MAX(timestamp)) FROM recommendations\")
    r = c.fetchone()[0]
    print(r if r is not None else 999999)
except Exception as e:
    print(999999)
")
echo "last_row_age_seconds: $AGE"
if [ "$AGE" -lt 39600 ]; then
  echo "Last LLM-team signal <11h old; skipping Cowork run (intended cadence: 12h)."
  exit 0
fi
```

## 2. LIGHTWEIGHT DEPS

```bash
pip install -q pandas numpy --break-system-packages 2>&1 | tail -1
```

## 3. FETCH LIVE MARKET DATA (curl, NOT WebFetch)

**Do not use Binance** (`api.binance.com`, `fapi.binance.com`) — both are geo-blocked from the Cowork sandbox and will return HTTP 451 every time. Use the substitutes below.

**Throttle CoinGecko calls**: the free tier rate-limits after ~6 back-to-back requests. Sleep 2s between calls and retry once on HTTP 429 after 10s.

```bash
cg_get() {
  local url="$1" out="$2"
  curl -s -m 20 "$url" -o "$out"
  if grep -q '"error_code":429' "$out" 2>/dev/null; then
    sleep 10
    curl -s -m 20 "$url" -o "$out"
  fi
  sleep 2
}

# Batched spot snapshot — ONE call for all three coins
cg_get "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,rocket-pool&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true" "$SCRATCH/cg_simple.json"

# Per-coin details (for ATH, 7d/30d changes, high/low)
for sym_pair in "BTC:bitcoin" "ETH:ethereum" "RPL:rocket-pool"; do
  sym="${sym_pair%%:*}"; cgid="${sym_pair##*:}"
  cg_get "https://api.coingecko.com/api/v3/coins/${cgid}?localization=false&tickers=false&community_data=false&developer_data=false" "$SCRATCH/cg_${sym}.json"
done

# OHLC — prefer Kraken for BTC/ETH (no rate limit, no geo-block), CoinGecko for RPL
# Kraken 1h (interval=60), 240 bars ≈ 10 days
curl -s -m 20 "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60" -o "$SCRATCH/kraken_BTC_1h.json"
curl -s -m 20 "https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=60" -o "$SCRATCH/kraken_ETH_1h.json"
curl -s -m 20 "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=240" -o "$SCRATCH/kraken_BTC_4h.json"
curl -s -m 20 "https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=240" -o "$SCRATCH/kraken_ETH_4h.json"

# RPL — Crypto.com Exchange MCP primary (clean 4h candles for RPL_USD; eliminates
# Coinbase's "Unsupported granularity" reject on 14400). Coinbase 1h re-aggregated
# to 4h is the secondary fallback; CoinGecko market_chart is tertiary.
#
# Call the Crypto.com Exchange MCP connector's `get_candlestick` tool (NOT curl —
# the tool name in the deferred-tools list is `mcp__*__get_candlestick` with a UUID
# prefix; load via ToolSearch keyword "candlestick" if not already loaded).
# Args: { instrument_name: "RPL_USD", timeframe: "4h" }. Returns up to 50 bars
# in the form {"data":[{"timestamp":"ISO","open","high","low","close","volume","volume_usd"}, ...]}.
# Write the raw JSON to $SCRATCH/cryptocom_RPL_4h.json so §4 can read it.
# 50 bars covers ~8 days of 4h candles — fine for RSI/MACD/BB/EMA-50 on RPL.
# (RPL never had ema_200 coverage anyway: would need ~33 days of 4h history.)
#
# Also call `get_ticker` for BTC_USD, ETH_USD, RPL_USD and write the combined
# response (keyed by instrument_name) to $SCRATCH/cryptocom_tickers.json — used
# in §6 as a spot cross-check vs CoinGecko (>2% deviation -> `cg-stale-<SYM>` tag).
#
# Coinbase 1h is the secondary path (re-aggregated to 4h in §4):
curl -s -m 20 "https://api.exchange.coinbase.com/products/RPL-USD/candles?granularity=3600" -o "$SCRATCH/coinbase_RPL_1h.json"
if ! grep -q '^\[\[' "$SCRATCH/coinbase_RPL_1h.json"; then
  cg_get "https://api.coingecko.com/api/v3/coins/rocket-pool/market_chart?vs_currency=usd&days=14" "$SCRATCH/cg_RPL_chart.json"
fi

# Funding rates — Bybit (not geo-blocked) for BTC/ETH
curl -s -m 15 "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=1" -o "$SCRATCH/bybit_BTC_fund.json"
curl -s -m 15 "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=ETHUSDT&limit=1" -o "$SCRATCH/bybit_ETH_fund.json"

# Open interest — Bybit
curl -s -m 15 "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=4h&limit=1" -o "$SCRATCH/bybit_BTC_oi.json"
curl -s -m 15 "https://api.bybit.com/v5/market/open-interest?category=linear&symbol=ETHUSDT&intervalTime=4h&limit=1" -o "$SCRATCH/bybit_ETH_oi.json"

# Fear & Greed — once per run
curl -s -m 10 "https://api.alternative.me/fng/?limit=1" -o "$SCRATCH/fng.json"
```

If any endpoint fails, note it in the degraded-data tags (§6) and continue.

## 4. COMPUTE INDICATORS USING THE REPO'S MODULE

Use the project's `indicators.py` so Cowork numbers match the local runner's numbers exactly. Inspect the signature first if unsure.

```bash
python3 << PY
import sys, json, os
sys.path.insert(0, "$WORKSPACE")
import pandas as pd, numpy as np
import inspect
from indicators import compute_all_indicators

def kraken_to_df(path):
    d = json.load(open(path))
    if d.get("error"): return None
    result = d["result"]
    # Find the OHLC array (first key that isn't "last")
    key = next(k for k in result if k != "last")
    rows = result[key]  # [time, open, high, low, close, vwap, volume, count]
    df = pd.DataFrame(rows, columns=["t","o","h","l","c","vwap","v","n"])
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

def cryptocom_to_df(path):
    """Crypto.com Exchange get_candlestick output -> OHLCV df (oldest-first).
    Schema: {"data":[{"timestamp","open","high","low","close","volume","volume_usd"}, ...]}
    Up to 50 bars per call; sufficient for RSI/MACD/BB/EMA-50 on RPL 4h."""
    if not os.path.exists(path) or os.path.getsize(path) < 50: return None
    d = json.load(open(path))
    rows = d.get("data") or []
    if not rows: return None
    df = pd.DataFrame(rows)
    df = df.rename(columns={"open":"o","high":"h","low":"l","close":"c","volume":"v"})
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["o","h","l","c","v"]]

def coinbase_to_df(path):
    d = json.load(open(path))
    if not isinstance(d, list) or not d: return None
    # Coinbase returns newest-first: [time, low, high, open, close, volume]
    df = pd.DataFrame(d, columns=["t","l","h","o","c","v"]).iloc[::-1].reset_index(drop=True)
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

def coinbase_1h_to_4h(path):
    """Coinbase 1h candles re-aggregated to 4h (Coinbase rejects granularity=14400)."""
    if not os.path.exists(path) or os.path.getsize(path) < 50: return None
    d = json.load(open(path))
    if not isinstance(d, list) or not d: return None
    df = pd.DataFrame(d, columns=["t","l","h","o","c","v"]).iloc[::-1].reset_index(drop=True)
    df["t"] = pd.to_datetime(df["t"], unit="s")
    df = df.set_index("t")
    df[["l","h","o","c","v"]] = df[["l","h","o","c","v"]].astype(float)
    agg = df.resample("4h").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
    return agg.reset_index(drop=True)

def cg_chart_to_df(path):
    d = json.load(open(path))
    if "prices" not in d: return None
    # hourly close series → synthesize OHLC from consecutive closes
    prices = d["prices"]  # [[ms, price], ...]
    df = pd.DataFrame(prices, columns=["t","c"])
    df["o"] = df["c"].shift(1).fillna(df["c"])
    df["h"] = df[["o","c"]].max(axis=1)
    df["l"] = df[["o","c"]].min(axis=1)
    df["v"] = 0.0
    return df[["t","o","h","l","c","v"]]

loaders = {
    "BTC": lambda: kraken_to_df("$SCRATCH/kraken_BTC_4h.json"),
    "ETH": lambda: kraken_to_df("$SCRATCH/kraken_ETH_4h.json"),
    "RPL": lambda: (
        # Primary: Crypto.com 4h (clean ~50 bars, no granularity issues)
        cryptocom_to_df("$SCRATCH/cryptocom_RPL_4h.json")
        or coinbase_1h_to_4h("$SCRATCH/coinbase_RPL_1h.json")  # Secondary
        or cg_chart_to_df("$SCRATCH/cg_RPL_chart.json")        # Tertiary
    ),
}

out = {}
sig = inspect.signature(compute_all_indicators)
print("compute_all_indicators signature:", sig)
for sym, loader in loaders.items():
    try:
        df = loader()
        if df is None or len(df) < 30:
            out[sym] = {"error": "insufficient bars"}
            continue
        ind = compute_all_indicators(df)
        # Coerce to JSON-serializable
        out[sym] = json.loads(json.dumps(ind, default=str))
    except Exception as e:
        out[sym] = {"error": str(e)}
        print(f"{sym} indicators failed: {e}")

json.dump(out, open("$SCRATCH/indicators.json","w"), indent=2)
print(json.dumps(out, indent=2)[:2000])
PY
```

If `compute_all_indicators` has a different signature or fails, fall back to this inline implementation (keep identical math):

```python
# Fallback if the repo function is unavailable.
def _rsi(c, n=14):
    import numpy as np
    diff = np.diff(c); g = np.where(diff>0,diff,0); l = np.where(diff<0,-diff,0)
    ag = g[-n:].mean(); al = l[-n:].mean()
    return 100 - 100/(1+ag/al) if al>0 else 100
def _ema(arr, p):
    k = 2/(p+1); e = arr[0]
    for x in arr[1:]: e = x*k + e*(1-k)
    return e
```

## 4.5. COMPUTE GUARDRAIL CONTEXT (2026-04-20 lookback recommendations)

The 2026-04-20 weekly lookback surfaced three recurring failures the
prior skill did not prevent: (a) 96/94/91% LONG bias with sub-35% win
rates, (b) REX trading his own book (28/28 LONG on BTC), (c) ZEN firing
lone-SHORT fades on vibes and losing. This section computes three
per-(analyst, coin) context blocks — exposure, cooldown, and confidence
calibration — that MUST be injected into each analyst's roleplay in §5.
The blocks are read-only SQLite queries against `recommendations.db`
(no new schema, no writes).

Thresholds:
- Exposure WARN: same-direction open notional ≥ 10% of $124K portfolio
- Exposure HARD CAP: ≥ 15% — downstream analysts MUST downgrade or ≤0.5%
- Cooldown window: 12h after a CLOSED losing position on that coin
- Calibration window: rolling 30 days, min 4 closed calls per conf bucket

```bash
python3 << 'PY'
import sqlite3, json, os
WORKSPACE = os.environ.get("WORKSPACE") or "$WORKSPACE"
SCRATCH   = os.environ.get("SCRATCH")   or "$SCRATCH"

PORTFOLIO_SIZE = 124_000
EXPOSURE_WARN_PCT = 3.0    # v2: was 10.0
EXPOSURE_CAP_PCT  = 5.0    # v2: was 15.0
COOLDOWN_HOURS    = 12
CALIBRATION_DAYS  = 30
CALIBRATION_MIN_N = 4
COINS    = ["BTC", "ETH"]   # v2: RPL dropped (liquidity mismatch)
ANALYSTS = ["ARIA","MARCUS","NOVA","VEGA","DELTA","CHAIN",
            "QUANT","DEFI","ATLAS","REX","ZEN"]

conn = sqlite3.connect(f"{WORKSPACE}/recommendations.db", timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def exposure_block(sym):
    rows = cur.execute(
        "SELECT analyst, recommendation, position_size_usd "
        "FROM recommendations WHERE status='OPEN' AND symbol=?",
        (sym,),
    ).fetchall()
    longs, shorts = [], []
    l_usd = s_usd = 0.0
    for r in rows:
        d = (r["recommendation"] or "").upper()
        usd = r["position_size_usd"] or 0.0
        if d == "LONG":  longs.append(r["analyst"]);  l_usd += usd
        elif d == "SHORT": shorts.append(r["analyst"]); s_usd += usd
    l_pct = l_usd / PORTFOLIO_SIZE * 100
    s_pct = s_usd / PORTFOLIO_SIZE * 100
    if l_pct < EXPOSURE_WARN_PCT and s_pct < EXPOSURE_WARN_PCT and not (longs and shorts):
        return ""
    lines = ["=== OPEN BOOK EXPOSURE — PRE-CALL CHECK ==="]
    if l_pct >= EXPOSURE_WARN_PCT:
        sev = "HARD CAP" if l_pct >= EXPOSURE_CAP_PCT else "WARNING"
        lines.append(
            f"  {sev}: {sym} LONG book at {l_pct:.1f}% of ${PORTFOLIO_SIZE:,} "
            f"({len(longs)} open calls by {', '.join(sorted(set(longs)))})."
        )
        if l_pct >= EXPOSURE_CAP_PCT:
            lines.append(
                f"  If your call is LONG {sym}, you MUST downgrade to WATCH or "
                f"size ≤0.5% (${PORTFOLIO_SIZE*0.005:,.0f}). This is not a suggestion."
            )
        else:
            lines.append(
                f"  If your call is LONG {sym}, halve your sizing or require a "
                "fresh non-overlapping thesis."
            )
    if s_pct >= EXPOSURE_WARN_PCT:
        sev = "HARD CAP" if s_pct >= EXPOSURE_CAP_PCT else "WARNING"
        lines.append(
            f"  {sev}: {sym} SHORT book at {s_pct:.1f}% of ${PORTFOLIO_SIZE:,} "
            f"({len(shorts)} open calls)."
        )
        if s_pct >= EXPOSURE_CAP_PCT:
            lines.append(f"  If your call is SHORT {sym}, downgrade to WATCH or ≤0.5%.")
    if longs and shorts:
        lines.append(
            f"  CONFLICT: {len(longs)}L vs {len(shorts)}S open on {sym} — "
            "team is already hedging itself into noise."
        )
    lines.append("=" * 44)
    return "\n".join(lines)

def cooldown_block(sym):
    rows = cur.execute(
        "SELECT analyst, recommendation, outcome_pct, thesis, "
        " (julianday('now') - julianday(REPLACE(closed_at,'T',' '))) * 24 AS hrs "
        "FROM recommendations "
        "WHERE status='CLOSED' AND symbol=? AND outcome_pct IS NOT NULL "
        "  AND outcome_pct < 0 AND closed_at IS NOT NULL "
        "  AND (julianday('now') - julianday(REPLACE(closed_at,'T',' '))) * 24 <= ? "
        "ORDER BY closed_at DESC",
        (sym, COOLDOWN_HOURS),
    ).fetchall()
    if not rows:
        return ""
    lines = [f"=== RECENT CLOSED LOSSES ON {sym} (last {COOLDOWN_HOURS}h) ==="]
    for r in rows[:4]:
        lines.append(
            f"  {r['analyst']} {r['recommendation']} closed "
            f"{r['outcome_pct']:+.1f}% {r['hrs']:.1f}h ago. "
            f"Thesis: {(r['thesis'] or '')[:140]}"
        )
    lines.append(
        "  If your call matches a direction above, you MUST either (a) cite a "
        "NEW signal absent from the losing thesis or (b) downgrade to WATCH. "
        "Reflex re-entry was the single biggest P&L leak in the 4/20 lookback."
    )
    lines.append("=" * 44)
    return "\n".join(lines)

def calibration_block(analyst, sym):
    rows = cur.execute(
        "SELECT confidence, outcome_pct FROM recommendations "
        "WHERE analyst=? AND symbol=? AND status='CLOSED' "
        "  AND outcome_pct IS NOT NULL AND confidence IS NOT NULL "
        "  AND timestamp >= datetime('now', ?)",
        (analyst, sym, f"-{CALIBRATION_DAYS} days"),
    ).fetchall()
    buckets = {}
    for r in rows:
        buckets.setdefault(int(r["confidence"]), []).append(float(r["outcome_pct"]))
    data = {}
    for c, pcts in buckets.items():
        if len(pcts) < CALIBRATION_MIN_N:
            continue
        wins = sum(1 for p in pcts if p > 0)
        data[c] = (len(pcts), wins, wins / len(pcts), sum(pcts) / len(pcts))
    if not data:
        return ""
    lines = [f"=== YOUR {CALIBRATION_DAYS}d CONFIDENCE CALIBRATION — {analyst} on {sym} ==="]
    for c in sorted(data):
        n, wins, wr, avg = data[c]
        lines.append(f"  conf={c}: win_rate={wr:.0%}  avg_outcome={avg:+.2f}%  n={n}")
    lines.append(
        "  If your conf=N bucket has a sub-25% win rate above, a conf=N call "
        "today is likely overconfidence — downgrade the conf unless you can "
        "cite a signal absent from your prior losing calls."
    )
    lines.append("=" * 44)
    return "\n".join(lines)

# Pre-compute all (analyst, coin) blocks
guardrails = {}
for sym in COINS:
    exp = exposure_block(sym)
    cd  = cooldown_block(sym)
    for a in ANALYSTS:
        calib = calibration_block(a, sym)
        blocks = [b for b in (exp, cd, calib) if b]
        guardrails[f"{a}:{sym}"] = "\n\n".join(blocks) if blocks else ""

conn.close()
json.dump(guardrails, open(f"{SCRATCH}/guardrails.json", "w"), indent=2)

# Dump a human-visible summary so the roleplay context includes the blocks
print("=== GUARDRAIL CONTEXT SUMMARY ===")
for sym in COINS:
    # print the shared exposure + cooldown context once per coin
    aria_block = guardrails.get(f"ARIA:{sym}", "")
    if aria_block:
        # Strip calibration section (that's per-analyst)
        shared_lines = []
        for section in aria_block.split("\n\n"):
            if "CONFIDENCE CALIBRATION" not in section:
                shared_lines.append(section)
        if shared_lines:
            print(f"\n--- {sym} shared context ---")
            print("\n\n".join(shared_lines))
    else:
        print(f"\n--- {sym} --- (quiet book, no exposure/cooldown flags)")

# And a few representative per-analyst calibrations
for pair in ("ARIA:BTC","NOVA:ETH","ZEN:RPL","REX:ETH"):
    block = guardrails.get(pair, "")
    calib_section = [s for s in block.split("\n\n") if "CONFIDENCE CALIBRATION" in s]
    if calib_section:
        print(f"\n--- calibration [{pair}] ---")
        print(calib_section[0])
PY
```

**What §5 must do with this JSON.** Before writing any analyst's roleplay
output, open `$SCRATCH/guardrails.json` and look up the key
`"<ANALYST>:<COIN>"`. The value is either:
- An empty string → the book is quiet, proceed normally.
- A text block containing one or more of: exposure warning, cooldown
  warning, confidence calibration. Every one of these lines is mandatory
  context — your analyst must visibly respect these rules in both thesis
  and sizing, not just acknowledge them. Contradicting a HARD CAP or
  firing into a cooldown window without a new signal is an error.

## 5. THE 11-ANALYST INLINE ANALYSIS

Roleplay each analyst, inserting that analyst's guardrail block (from
`$SCRATCH/guardrails.json["<ANALYST>:<COIN>"]`) into their reasoning
before they produce a thesis. Keep each output under ~200 words.
Portfolio size is **$124,000**. Each analyst MUST end with a signal
line in exactly this format:

```
[SIGNAL: LONG|SHORT|WATCH|AVOID|NEUTRAL | CONFIDENCE: N | TARGET: $X | STOP: $Y | SIZE: P% ($USD) | THESIS: one-sentence rationale]
```

### Cohort structure (2026-04-20 lookback recommendation)

To break the ordering-bias cascade that drove the 7% ETH LONG win rate
last week, split the 11 analysts into two cohorts:

**COHORT 1 — "blind" seats (derive independently from market data only):**
ARIA, MARCUS, NOVA, VEGA, DELTA

When writing any cohort-1 analyst, you MUST derive that analyst's call
from the market data + their guardrail block ONLY. Do NOT reference
any other cohort-1 analyst's prior output, even implicitly. Each
cohort-1 analyst should read as if they have never seen the other four
in this round. Randomize the order in which you emit cohort 1 (e.g.
roll VEGA first one run, NOVA first the next) so no single seat anchors
the top of the report every time — pick a different order each run.

**COHORT 2 — synthesizers (see cohort 1 outputs):**
CHAIN, QUANT, DEFI, ATLAS, REX, ZEN

Cohort 2 runs sequentially and SHOULD reference cohort 1 — those roles
are explicit synthesizers. Keep this order exactly so REX's directive
can flow into ZEN.

### Roster (roleplay per cohort structure above)

1. **ARIA** — Technical (RSI, MACD, BB, EMA trends). *Cohort 1 — blind.*
2. **MARCUS** — Tape reader (volume, order flow, price action). *Cohort 1 — blind.*
3. **NOVA** — Macro/catalyst/sentiment (Fear & Greed, news, funding rate direction). *Cohort 1 — blind.*
4. **VEGA** — Derivatives/options. Only BTC & ETH have options depth — for RPL emit `WATCH` with thesis "no liquid options market". *Cohort 1 — blind.*
5. **DELTA** — Futures/perpetuals (OI from Bybit, funding rate direction, liquidation clusters). *Cohort 1 — blind.*
6. **CHAIN** — On-chain flows, MVRV, whale activity (inferred from public data). *Cohort 2.*
7. **QUANT** — Correlations, vol regime, statistical edges. *Cohort 2.*
8. **DEFI** — TVL, protocol revenue, token unlocks (especially relevant for RPL). *Cohort 2.*
9. **ATLAS** — Geopolitical/regulatory (SEC, ETF flows, policy). *Cohort 2.*

10. **REX** — Risk manager. *Cohort 2.* CRITICAL accountability framing:
    the 2026-04-13..19 lookback showed you went LONG 28/28 on BTC and
    27/1 on ETH — a 0% challenge rate. That is trading the team's
    narrative, not risk management. When the book exposure block shows
    same-direction exposure on this coin ≥10% of portfolio, your default
    must be WATCH or a reduced-size contrary call — not another add.
    Being disagreeable when the book is lopsided is the job.

    **Required output — EXPOSURE_BLOCK directive.** Immediately BEFORE
    your `[SIGNAL: ...]` line, emit EXACTLY ONE line in this format:
    - `EXPOSURE_BLOCK: YES`   → book is over-extended; ZEN MUST downgrade/shrink
    - `EXPOSURE_BLOCK: NO`    → headroom exists; normal sizing applies

    Say YES whenever: (a) the exposure block in your context shows any
    same-direction notional ≥10% of portfolio on this coin, OR (b) 5+
    of the 9 prior analysts (cohorts 1 + 2) in this round are already
    pointing the same direction. Say NO only when you are actively
    clearing the trade. The downstream parser requires this directive —
    omitting it is an error logged as `rex-missing-exposure-block-<SYM>`.

11. **ZEN** — Contrarian. *Cohort 2.* GATED — you may publish a LONG or
    SHORT signal ONLY if at least ONE of the following numeric triggers
    is true for this coin, and you MUST cite its actual value from the
    live data:

    - Funding rate > 0.05%  (longs crowded)  → supports SHORT
    - Funding rate < −0.05% (shorts crowded) → supports LONG
    - Fear & Greed ≥ 75  (extreme greed)     → supports SHORT
    - Fear & Greed ≤ 25  (extreme fear)      → supports LONG
    - Put/Call > 1.3  (put-heavy)            → supports LONG
    - Put/Call < 0.6  (call-heavy)           → supports SHORT
    - 7+ analysts in this round already aligned the same direction → may
      support a fade, but still requires ONE of the above as well

    If NO numeric trigger is true, your signal MUST be WATCH or NEUTRAL.
    Do NOT fade on intuition — the 4/20 lookback showed your lone-fade
    losses averaged −4% on ETH. Cite the trigger value explicitly
    (e.g. "F&G=22 — extreme fear contrarian LONG").

    **REX directive parsing.** BEFORE writing ZEN's output for this coin,
    scan REX's immediately-preceding output for the string
    `EXPOSURE_BLOCK: YES` or `EXPOSURE_BLOCK: NO` (case-insensitive).
    If YES, prepend to your reasoning: "REX has flagged the book
    over-extended — any directional call I emit must downgrade to WATCH
    or size ≤0.5%." If the directive is missing from REX's output,
    append the tag `rex-missing-exposure-block-<SYM>` to the degraded
    tags in §6.

Run this for each coin in {BTC, ETH, RPL} → 33 analyst outputs total.

Also write the full analysis markdown to `$WORKSPACE/cowork_analysis_${RUN_ID}.md` (for human review).

## 6. PARSE SIGNALS AND WRITE TO DB (inline Python only)

Use the correct ISO timestamp format (`YYYY-MM-DDTHH:MM:SS+00:00`) — the dashboard queries assume it. Tag degraded runs so the dashboard can distinguish them.

```python
import sqlite3, json, os
from datetime import datetime, timezone

TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

# Collect failure flags based on what §3 / §4 / §4.5 / §5 actually produced
tags = ["cowork-fallback", "guardrails-v1"]
if not os.path.exists(f"{SCRATCH}/bybit_BTC_fund.json") or os.path.getsize(f"{SCRATCH}/bybit_BTC_fund.json") < 50:
    tags.append("no-funding")
ind = json.load(open(f"{SCRATCH}/indicators.json"))
for sym in ("BTC","ETH","RPL"):
    if ind.get(sym, {}).get("error"):
        tags.append(f"no-indicators-{sym}")

# Crypto.com spot cross-check vs CoinGecko — flag >2% deviation as cg-stale-<SYM>.
# Best-effort: missing tickers JSON is not an error.
try:
    cdc = json.load(open(f"{SCRATCH}/cryptocom_tickers.json"))
    cg  = json.load(open(f"{SCRATCH}/cg_simple.json"))
    pairs = {"BTC": ("BTC_USD","bitcoin"), "ETH": ("ETH_USD","ethereum"), "RPL": ("RPL_USD","rocket-pool")}
    for sym, (cdc_inst, cg_id) in pairs.items():
        cdc_px = float((cdc.get(cdc_inst) or {}).get("last", 0)) or None
        cg_px  = float((cg.get(cg_id)    or {}).get("usd", 0))  or None
        if cdc_px and cg_px and abs(cdc_px - cg_px) / cg_px > 0.02:
            tags.append(f"cg-stale-{sym}")
except Exception:
    pass

# Tag any REX response that failed to emit the EXPOSURE_BLOCK directive.
# The flag `rex-missing-exposure-block-<SYM>` is the canonical signal that the
# roleplay ignored the 2026-04-20 guardrail contract for that coin.
import re
_EB_RE = re.compile(r"EXPOSURE_BLOCK\s*:\s*(YES|NO)", re.IGNORECASE)
rex_outputs = locals().get("rex_outputs_per_coin", {})   # {sym: rex_text}
for sym, txt in rex_outputs.items():
    if not _EB_RE.search(txt or ""):
        tags.append(f"rex-missing-exposure-block-{sym}")

tags_json = json.dumps(tags)

conn = sqlite3.connect(f"{WORKSPACE}/recommendations.db", timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
cur = conn.cursor()

# Signals list (analyst, symbol, rec, entry, target, stop, conf, thesis, size_pct, size_usd)
# ... build from parsed analyst output, filter LONG/SHORT only ...
for s in signals:
    cur.execute("""INSERT INTO recommendations
        (timestamp, analyst, symbol, recommendation, entry_price, target_price,
         stop_loss, confidence, thesis, status, position_size_pct, position_size_usd, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)""",
        (TS, *s, tags_json))
conn.commit()
conn.close()
```

Confirm schema beforehand via Python (no `sqlite3` CLI):
```python
import sqlite3
conn = sqlite3.connect("recommendations.db")
conn.execute("PRAGMA journal_mode=WAL")
print(conn.execute(
    "SELECT sql FROM sqlite_master WHERE name='recommendations'").fetchone()[0])
```

## 7. AUTO-CLOSE HIT POSITIONS

Call the existing tracker logic and *log the return value* so we can tell success from silent failure:

```python
import sys, traceback
sys.path.insert(0, WORKSPACE)
try:
    from tracker import check_and_close_positions
    for sym, price in [("BTC", BTC_PRICE), ("ETH", ETH_PRICE), ("RPL", RPL_PRICE)]:
        try:
            closed = check_and_close_positions(sym, price)
            n = len(closed) if hasattr(closed, "__len__") else closed
            print(f"close {sym} @ ${price}: {n} positions closed")
        except Exception as e:
            print(f"close {sym} failed: {e}"); traceback.print_exc()
except Exception as e:
    print(f"tracker import failed: {e}")
```

Run this BEFORE inserting new rows (§6) so closes don't race with the new OPENs.

## 8. COMMIT AND PUSH — ALWAYS FROM A FRESH CLONE

The workspace `.git` is unreliable (stale Windows locks, occasional index corruption, frequent divergence from `origin/master`). Do not commit from the workspace. Clone shallow into scratch, apply the DB, commit, push.

```bash
# Get remote URL without leaking the PAT into logs
REMOTE=$(cd "$WORKSPACE" && git config --get remote.origin.url)
REMOTE_DISPLAY=$(echo "$REMOTE" | sed 's|://[^@]*@|://|')
echo "push target: $REMOTE_DISPLAY"

rm -rf "$SCRATCH/push" 2>/dev/null
git clone --depth 2 "$REMOTE" "$SCRATCH/push" 2>&1 | tail -3

# Copy the DB we just wrote in §6/§7 into the clone
cp "$WORKSPACE/recommendations.db" "$SCRATCH/push/recommendations.db"

cd "$SCRATCH/push"
git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Fallback" add recommendations.db
if git diff --cached --quiet; then
  echo "no DB changes to commit"
  COMMIT_SHA="(none)"; PUSH_STATUS="skipped"
else
  git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Fallback" commit -m "Cowork 4h analysis $RUN_ID" 2>&1 | tail -3
  COMMIT_SHA=$(git rev-parse --short HEAD)
  PUSH_OUT=$(git push 2>&1 | tail -3)
  echo "$PUSH_OUT"
  if echo "$PUSH_OUT" | grep -q "rejected\|error:"; then PUSH_STATUS="failed"; else PUSH_STATUS="ok"; fi

  # Mirror the pushed DB back to the workspace so local state matches origin
  cp "$SCRATCH/push/recommendations.db" "$WORKSPACE/recommendations.db"
fi
cd "$WORKSPACE"
```

Only commit `recommendations.db`. Never touch `.py` files.

## 9. RUN HEARTBEAT LOG

Write a small JSON log so failures between fetch and insert leave a trace:

```python
import json, os
os.makedirs(f"{WORKSPACE}/cowork_runs", exist_ok=True)
log = {
    "run_id": RUN_ID,
    "started": START_TS,
    "ended": datetime.now(timezone.utc).isoformat(timespec="seconds") + "+00:00",
    "coins": ["BTC","ETH","RPL"],
    "failures": tags,          # from §6
    "rows_written": len(signals),
    "commit_sha": COMMIT_SHA,
    "push_status": PUSH_STATUS,
    "prices": {"BTC": BTC_PRICE, "ETH": ETH_PRICE, "RPL": RPL_PRICE},
}
json.dump(log, open(f"{WORKSPACE}/cowork_runs/{RUN_ID}.json","w"), indent=2)
```

## 9b. SAVE FULL REPORT TO DB

Persist the full markdown report and heartbeat to `analysis_reports` so the
dashboard's "Analysis History" page can display it. Use the project's
`tracker.save_analysis_report()` or inline SQL:

```python
import sys, json, sqlite3
sys.path.insert(0, WORKSPACE)
try:
    from tracker import save_analysis_report, init_db
    init_db()
    save_analysis_report(
        run_id=RUN_ID,
        timestamp=TS,
        coins=["BTC","ETH","RPL"],
        report_md=open(f"{WORKSPACE}/cowork_analysis_{RUN_ID}.md").read(),
        prices={"BTC": BTC_PRICE, "ETH": ETH_PRICE, "RPL": RPL_PRICE},
        fear_greed=FNG_VALUE,         # integer from §3
        signals_count=len(signals),
        tags=tags,
        heartbeat=log,                # dict from §9
        source="cowork",
    )
    print(f"Report saved to analysis_reports (run_id={RUN_ID})")
except Exception as e:
    print(f"save_analysis_report failed: {e}")
    # Fallback: write directly to the fresh-clone DB in §8
    try:
        conn = sqlite3.connect(f"{SCRATCH}/push/recommendations.db", timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS analysis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
            timestamp TEXT NOT NULL, coins TEXT NOT NULL, prices TEXT,
            fear_greed INTEGER, signals_count INTEGER DEFAULT 0, tags TEXT,
            report_md TEXT NOT NULL, heartbeat TEXT, source TEXT DEFAULT 'cowork')""")
        conn.execute(
            "INSERT OR REPLACE INTO analysis_reports (run_id,timestamp,coins,prices,fear_greed,signals_count,tags,report_md,heartbeat,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (RUN_ID, TS, json.dumps(["BTC","ETH","RPL"]),
             json.dumps({"BTC":BTC_PRICE,"ETH":ETH_PRICE,"RPL":RPL_PRICE}),
             FNG_VALUE, len(signals), json.dumps(tags),
             open(f"{WORKSPACE}/cowork_analysis_{RUN_ID}.md").read(),
             json.dumps(log), "cowork"))
        conn.commit(); conn.close()
        print("Report saved to clone DB (fallback)")
    except Exception as e2:
        print(f"Fallback DB write also failed: {e2}")
```

## 10. FINAL REPORT

Output a concise summary:
- Workspace path used
- Skip-if-fresh result (skipped or proceeded + age in seconds)
- Data sources that succeeded vs. failed (Kraken/Coinbase/Bybit/CG/FNG)
- **Guardrail state per coin** (from §4.5): which coins had an exposure
  WARN or HARD CAP active, which coins had cooldown hits, count of
  (analyst, coin) pairs with a calibration block emitted
- **REX directive** per coin: `YES` / `NO` / `MISSING`
- Signals saved per coin (LONG/SHORT counts)
- Positions closed by `check_and_close_positions` per coin
- Commit SHA and push status (ok / skipped / failed)
- Streamlit redeploy URL: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/
- Heartbeat log path

## CONSTRAINTS AND GOTCHAS

- **Do NOT call Binance endpoints.** They are geo-blocked in the Cowork sandbox (HTTP 451). Use Kraken / Coinbase / OKX / Crypto.com Exchange (MCP)