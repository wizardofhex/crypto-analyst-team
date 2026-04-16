---
name: crypto-4h-analysis-cowork
description: Cowork fallback — produce an 11-analyst crypto analysis for BTC/ETH/RPL, persist signals, push DB to GitHub.
---

You are the crypto-analyst-team running autonomously inside Cowork. Your job is to produce an 11-analyst market analysis for BTC, ETH, and RPL, persist signals to the project SQLite database, and push the updated DB to GitHub so the Streamlit Cloud dashboard redeploys. This is a fallback for the user's local Python runner (`run_scheduled_analysis.py`) which fires on the same 4-hour cron 30 minutes earlier. If the local runner already succeeded, detect that and exit quickly.

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
if [ "$AGE" -lt 2700 ]; then
  echo "Local runner already produced fresh signals (<45m old); skipping Cowork fallback."
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

# RPL — Coinbase first (no rate limit), CoinGecko as fallback
curl -s -m 20 "https://api.exchange.coinbase.com/products/RPL-USD/candles?granularity=14400" -o "$SCRATCH/coinbase_RPL_4h.json"
if ! grep -q '^\[\[' "$SCRATCH/coinbase_RPL_4h.json"; then
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

def coinbase_to_df(path):
    d = json.load(open(path))
    if not isinstance(d, list) or not d: return None
    # Coinbase returns newest-first: [time, low, high, open, close, volume]
    df = pd.DataFrame(d, columns=["t","l","h","o","c","v"]).iloc[::-1].reset_index(drop=True)
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    return df

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
        coinbase_to_df("$SCRATCH/coinbase_RPL_4h.json")
        if os.path.exists("$SCRATCH/coinbase_RPL_4h.json") and os.path.getsize("$SCRATCH/coinbase_RPL_4h.json") > 50
        else cg_chart_to_df("$SCRATCH/cg_RPL_chart.json")
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

## 5. THE 11-ANALYST INLINE ANALYSIS

Roleplay each analyst *in order*. Each sees the prior analysts' outputs. Keep each under ~200 words. Portfolio size is **$124,000**. Each analyst MUST end with a signal line in exactly this format:

```
[SIGNAL: LONG|SHORT|WATCH|AVOID|NEUTRAL | CONFIDENCE: N | TARGET: $X | STOP: $Y | SIZE: P% ($USD) | THESIS: one-sentence rationale]
```

Roster (run in this order):
1. **ARIA** — Technical (RSI, MACD, BB, EMA trends)
2. **MARCUS** — Tape reader (volume, order flow, price action)
3. **NOVA** — Macro/catalyst/sentiment (Fear & Greed, news, funding rate *direction*)
4. **VEGA** — Derivatives/options. Only BTC & ETH have options depth — for RPL emit `WATCH` with thesis "no liquid options market"
5. **DELTA** — Futures/perpetuals (OI from Bybit, funding rate direction, liquidation clusters)
6. **CHAIN** — On-chain flows, MVRV, whale activity (inferred from public data)
7. **QUANT** — Correlations, vol regime, statistical edges
8. **DEFI** — TVL, protocol revenue, token unlocks (especially relevant for RPL)
9. **ATLAS** — Geopolitical/regulatory (SEC, ETF flows, policy)
10. **REX** — Risk manager, sets stops/sizing/R:R given the above
11. **ZEN** — Contrarian, fades consensus if the other 10 are leaning hard one way

Run this for each coin in {BTC, ETH, RPL} → 33 analyst outputs total.

Also write the full analysis markdown to `$WORKSPACE/cowork_analysis_${RUN_ID}.md` (for human review).

## 6. PARSE SIGNALS AND WRITE TO DB (inline Python only)

Use the correct ISO timestamp format (`YYYY-MM-DDTHH:MM:SS+00:00`) — the dashboard queries assume it. Tag degraded runs so the dashboard can distinguish them.

```python
import sqlite3, json, os
from datetime import datetime, timezone

TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

# Collect failure flags based on what §3 and §4 actually produced
tags = ["cowork-fallback"]
if not os.path.exists(f"{SCRATCH}/bybit_BTC_fund.json") or os.path.getsize(f"{SCRATCH}/bybit_BTC_fund.json") < 50:
    tags.append("no-funding")
ind = json.load(open(f"{SCRATCH}/indicators.json"))
for sym in ("BTC","ETH","RPL"):
    if ind.get(sym, {}).get("error"):
        tags.append(f"no-indicators-{sym}")
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
- Signals saved per coin (LONG/SHORT counts)
- Positions closed by `check_and_close_positions` per coin
- Commit SHA and push status (ok / skipped / failed)
- Streamlit redeploy URL: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/
- Heartbeat log path

## CONSTRAINTS AND GOTCHAS

- **Do NOT call Binance endpoints.** They are geo-blocked in the Cowork sandbox (HTTP 451). Use Kraken / Coinbase / Bybit instead.
- **Do NOT use the `sqlite3` CLI.** It is not installed. Use inline Python.
- **Do NOT use WebFetch for JSON APIs.** It returns summarized markdown, not raw JSON. Use `curl`.
- **Do NOT commit from the workspace `.git`.** Stale Windows locks and index corruption will bite you. Always clone-in-scratch (§8).
- **Throttle CoinGecko** (2s between calls, one retry on 429 after 10s).
- **Timestamp format is ISO-8601 with T and `+00:00`** — other formats break dashboard sort/filter.
- **Only commit `recommendations.db`.** Never `.py` files, never the analysis markdown.
- **Degraded runs MUST be tagged** in the `tags` JSON column so the dashboard can filter them.
- **Target total runtime:** under 8 minutes.
- **On partial data, continue** — e.g. missing RPL indicators shouldn't block BTC/ETH signal writes.
