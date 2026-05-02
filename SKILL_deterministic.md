---
name: crypto-deterministic-strategy-cowork
description: Cowork-native runner for the v2-plan deterministic baseline (Strategy B). Pre-registered rule-based BTC/ETH long/short engine using indicators.py. 12h cadence, runs 5 minutes after the LLM team. Writes to recommendations_deterministic.
---

You are the v2-plan deterministic baseline (Strategy B) running in Cowork. Your
job is to evaluate four pre-registered rule patterns on BTC and ETH using the
project's `indicators.py` module, write any signals to the `recommendations_deterministic`
table, expire stale positions older than 48h, then push the updated DB to GitHub.

This skill runs in PARALLEL with the LLM team analysis (`SKILL.md`) on the same
12h cadence. They write to different tables and can run independently — if one
fails the other still produces data.

**The rules below are PRE-REGISTERED. They must NOT be tuned during the test
window.** That's the entire point of having a deterministic baseline: if the
rules can be tweaked retroactively, the comparison vs HODL and vs LLM-team is
meaningless.

## 0. WORKSPACE SETUP

```bash
WORKSPACE=$(ls -d /sessions/*/mnt/crypto_analyst_team 2>/dev/null | head -1)
[ -z "$WORKSPACE" ] && { echo "ERROR: workspace not found"; exit 1; }
cd "$WORKSPACE"

# Stale git locks (bindfs + Windows)
for f in $(find .git -name '*.lock' 2>/dev/null); do
  mv "$f" "${f}.stale.$(date +%s)" 2>/dev/null || true
done

RUN_ID=$(date -u +%Y%m%d_%H%MZ)
SCRATCH=/tmp/det_$RUN_ID
mkdir -p $SCRATCH
echo "workspace=$WORKSPACE scratch=$SCRATCH"
```

## 1. SKIP-IF-FRESH GUARD

If the local Python `run_deterministic_strategy.py` already wrote to
`recommendations_deterministic` in the last 6h, exit:

```bash
AGE=$(python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('recommendations.db', timeout=5)
    conn.execute('PRAGMA journal_mode=WAL')
    c = conn.cursor()
    c.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE name='recommendations_deterministic'\")
    if c.fetchone()[0] == 0:
        print(999999)
    else:
        c.execute(\"SELECT strftime('%s','now') - strftime('%s', MAX(timestamp)) FROM recommendations_deterministic\")
        r = c.fetchone()[0]
        print(r if r is not None else 999999)
except Exception:
    print(999999)
")
echo "deterministic_last_row_age_seconds: $AGE"
if [ "$AGE" -lt 21600 ]; then
  echo "Local deterministic runner already produced fresh signals (<6h old); skipping."
  exit 0
fi
```

## 2. DEPS

```bash
pip install -q pandas numpy --break-system-packages 2>&1 | tail -1
```

## 3. RUN THE STRATEGY VIA THE PROJECT'S MODULE

The cleanest way is to call the existing `run_deterministic_strategy.py` directly
since the rules live there. Cowork sandbox has Python and our repo is on disk.

```bash
# data_fetcher.py uses requests/CoinGecko/Kraken — all reachable from Cowork.
# Binance is geo-blocked but data_fetcher falls through gracefully.
python3 run_deterministic_strategy.py BTC ETH 2>&1 | tail -20
```

If `run_deterministic_strategy.py` is missing or fails, fall back to inline
evaluation below. Keep the rules byte-identical to the script — pre-registered.

## 4. INLINE FALLBACK (only if §3 failed)

```bash
python3 << 'PY'
import sys, json, sqlite3, os
from datetime import datetime, timezone
sys.path.insert(0, '.')
from data_fetcher import fetch_all_market_data
from indicators import calculate_all_indicators, calculate_atr
from config import DB_PATH

POSITION_SIZE_USD = 1240.0
MAX_CONCURRENT = 2
ATR_STOP = 1.5
ATR_TARGET = 3.0

# Ensure table exists
with sqlite3.connect(DB_PATH) as c:
    c.execute("""CREATE TABLE IF NOT EXISTS recommendations_deterministic (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        analyst TEXT NOT NULL, symbol TEXT NOT NULL, recommendation TEXT NOT NULL,
        entry_price REAL, target_price REAL, stop_loss REAL, confidence INTEGER,
        thesis TEXT, status TEXT DEFAULT 'OPEN', close_price REAL, outcome_pct REAL,
        closed_at TEXT, tags TEXT, position_size_pct REAL, position_size_usd REAL)""")

def open_count(c, sym, dirn):
    return c.execute("SELECT COUNT(*) FROM recommendations_deterministic "
                     "WHERE status='OPEN' AND symbol=? AND recommendation=?",
                     (sym, dirn)).fetchone()[0]

for sym in ('BTC', 'ETH'):
    md = fetch_all_market_data(sym)
    cg = md.get('coingecko') or {}
    price = cg.get('price')
    if not price:
        print(f"{sym}: no price -- skipping")
        continue
    df = (md.get('ohlcv') or {}).get('4h')
    if df is None or df.empty or len(df) < 50:
        print(f"{sym}: insufficient OHLCV -- skipping")
        continue
    ind = calculate_all_indicators(df, timeframe='4h')
    rsi, ema200 = ind.get('rsi'), ind.get('ema_200')
    atr, bb_pctb = ind.get('atr'), ind.get('bb_pct_b')
    last_bull, vol_pct = ind.get('last_candle_bullish'), ind.get('volume_ratio')
    funding = md.get('funding_rate') or 0.0
    try:
        atr_series = calculate_atr(df['high'], df['low'], df['close'])
        atr_ratio = atr / atr_series.tail(20).mean()
    except Exception:
        atr_ratio = 1.0

    signals = []
    if atr_ratio >= 1.0:
        if price > ema200 and 40 <= rsi <= 55 and abs(funding) <= 0.0005:
            signals.append(('LONG', 'trend_pullback_long',
                f"price ${price:.2f} > EMA200 ${ema200:.2f}, RSI={rsi}, ATR ratio={atr_ratio:.2f}x"))
        if price < ema200 and 45 <= rsi <= 60 and abs(funding) <= 0.0005:
            signals.append(('SHORT', 'trend_pullback_short',
                f"price ${price:.2f} < EMA200 ${ema200:.2f}, RSI={rsi}, ATR ratio={atr_ratio:.2f}x"))
    if bb_pctb and vol_pct and last_bull is not None:
        vol_mult = vol_pct / 100.0
        if bb_pctb < 5 and vol_mult > 3 and last_bull:
            signals.append(('LONG', 'capitulation_long',
                f"BB%B={bb_pctb} < 5, vol={vol_mult:.1f}x, bullish candle"))
        if bb_pctb > 95 and vol_mult > 3 and not last_bull:
            signals.append(('SHORT', 'blow_off_short',
                f"BB%B={bb_pctb} > 95, vol={vol_mult:.1f}x, bearish candle"))

    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as c:
        for direction, pattern, thesis in signals:
            if open_count(c, sym, direction) >= MAX_CONCURRENT:
                print(f"{sym} {direction} rejected (already at cap)"); continue
            stop = price - ATR_STOP * atr if direction == 'LONG' else price + ATR_STOP * atr
            target = price + ATR_TARGET * atr if direction == 'LONG' else price - ATR_TARGET * atr
            c.execute("""INSERT INTO recommendations_deterministic
                (timestamp, analyst, symbol, recommendation, entry_price, target_price,
                 stop_loss, confidence, thesis, status, tags, position_size_pct, position_size_usd)
                VALUES (?, 'DETERMINISTIC', ?, ?, ?, ?, ?, 7, ?, 'OPEN', ?, 1.0, ?)""",
                (ts, sym, direction, price, target, stop, thesis,
                 json.dumps(['deterministic-v1', f'pattern:{pattern}', 'cowork-fallback']),
                 1240.0))
            c.commit()
            print(f"{sym} {direction} saved -- pattern={pattern}")
PY
```

## 5. EXPIRE STALE POSITIONS (48h time-stop)

```bash
python3 << 'PY'
import sqlite3
from datetime import datetime, timezone, timedelta
from config import DB_PATH

# Approximate current prices from CoinGecko
import requests
r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd", timeout=10).json()
prices = {"BTC": r.get("bitcoin", {}).get("usd"), "ETH": r.get("ethereum", {}).get("usd")}

cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
ts_now = datetime.now(timezone.utc).isoformat()

with sqlite3.connect(DB_PATH) as c:
    c.row_factory = sqlite3.Row
    for sym, price in prices.items():
        if not price: continue
        rows = c.execute(
            "SELECT * FROM recommendations_deterministic WHERE status='OPEN' AND symbol=? AND timestamp <= ?",
            (sym, cutoff),
        ).fetchall()
        for r in rows:
            d = r["recommendation"]; e = r["entry_price"]
            pnl = round((price - e) / e * 100 if d == "LONG" else (e - price) / e * 100, 2)
            c.execute(
                "UPDATE recommendations_deterministic SET status='EXPIRED', close_price=?, outcome_pct=?, closed_at=? WHERE id=?",
                (price, pnl, ts_now, r["id"]),
            )
        c.commit()
        print(f"{sym}: expired {len(rows)} stale positions")
PY
```

## 6. PUSH (fresh-clone pattern)

```bash
REMOTE=$(git config --get remote.origin.url)
rm -rf "$SCRATCH/push" 2>/dev/null
git clone --depth 2 "$REMOTE" "$SCRATCH/push" 2>&1 | tail -2
cp recommendations.db "$SCRATCH/push/recommendations.db"
cd "$SCRATCH/push"
git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Deterministic" \
    add recommendations.db
if git diff --cached --quiet; then
  echo "No DB changes to commit"
else
  git -c user.email="cowork@diskoverdata.com" -c user.name="Cowork Deterministic" \
      commit -m "Deterministic Strategy B run $RUN_ID" 2>&1 | tail -2
  git push 2>&1 | tail -3
  cp recommendations.db "$WORKSPACE/recommendations.db"
fi
cd "$WORKSPACE"
```

## 7. FINAL REPORT

Output a one-line summary:
- Number of new signals saved per symbol
- Number of stale positions expired
- Commit SHA + push status
- Streamlit URL: https://crypto-analyst-team-pnf2pgrtweknvqkubxa6id.streamlit.app/

## CONSTRAINTS

- Do NOT modify the rule thresholds. Pre-registered means pre-registered.
- Do NOT call Binance (`api.binance.com`). data_fetcher.py uses Kraken/Coinbase fallbacks.
- Do NOT use the sqlite3 CLI. Inline Python only.
- Do NOT commit from the workspace `.git` directly — always fresh-clone in scratch.
- Target runtime: under 3 minutes.
