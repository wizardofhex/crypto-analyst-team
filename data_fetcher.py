"""
data_fetcher.py — Market data from CoinGecko, Binance, Coinbase, Alternative.me,
Deribit, CoinGlass, Blockchain.com, Glassnode, DeFiLlama, and more.
Falls back to yfinance when exchange APIs are unavailable.
"""

import os
import time
import logging
from typing import Dict, Any, Optional, List

import requests
import pandas as pd
import numpy as np

from config import COINGECKO_BASE, SYMBOL_TO_CG_ID

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.us/api/v3"
# Binance.US does not offer a futures/perpetuals API; funding rate is skipped gracefully.
COINBASE_BASE = "https://api.coinbase.com/api/v3/brokerage/market"
COINBASE_AUTH_BASE = "https://api.coinbase.com/api/v3/brokerage"
ALT_ME_BASE = "https://api.alternative.me"

REQUEST_TIMEOUT = 12  # seconds


# ─── Coinbase JWT auth (optional — falls back to public endpoints) ───────────


def _build_coinbase_jwt(method: str, path: str) -> Optional[str]:
    """Build a short-lived JWT for Coinbase CDP API authentication.
    The URI claim must match the request: 'GET api.coinbase.com/api/v3/...'
    Returns None if credentials are not configured.
    """
    api_key = os.environ.get("COINBASE_API_KEY", "")
    api_secret = os.environ.get("COINBASE_API_SECRET", "")
    if not api_key or not api_secret:
        return None

    try:
        import jwt  # PyJWT with cryptography backend
        import secrets

        # Unescape literal \n from .env into real newlines for PEM parsing
        secret = api_secret.replace("\\n", "\n")

        now = int(time.time())
        # Coinbase CDP requires URI = "METHOD host/path" (no scheme, no query params)
        uri = f"{method.upper()} api.coinbase.com{path}"

        payload = {
            "sub": api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        headers = {
            "kid": api_key,
            "nonce": secrets.token_hex(16),
            "typ": "JWT",
        }
        token = jwt.encode(payload, secret, algorithm="ES256", headers=headers)
        logger.debug("Coinbase JWT generated for %s", uri)
        return token
    except ImportError:
        logger.warning("PyJWT not installed — Coinbase auth disabled. pip install PyJWT cryptography")
        return None
    except Exception as e:
        logger.warning("Coinbase JWT generation failed: %s", e)
        return None


def _coinbase_auth_headers(method: str, path: str) -> Dict[str, str]:
    """Return headers for an authenticated Coinbase API request."""
    headers = {"Content-Type": "application/json"}
    token = _build_coinbase_jwt(method, path)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def coinbase_authenticated() -> bool:
    """Check whether Coinbase API credentials are configured."""
    return bool(os.environ.get("COINBASE_API_KEY")) and bool(os.environ.get("COINBASE_API_SECRET"))


def _get(url: str, params: dict = None, _is_retry: bool = False) -> Optional[dict]:
    """GET request with error handling; returns None on failure.
    On HTTP 429, sleeps 60s and retries once. If the retry also fails,
    returns {'_rate_limited': True} so callers can surface the gap.
    """
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            if not _is_retry:
                logger.warning("Rate limited (429) for %s — waiting 60s then retrying", url)
                time.sleep(60)
                return _get(url, params=params, _is_retry=True)
            else:
                logger.error("Rate limit persists after retry for %s", url)
                return {"_rate_limited": True}
        logger.warning("HTTP error %s for %s", e, url)
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error for %s", url)
    except requests.exceptions.Timeout:
        logger.warning("Timeout for %s", url)
    except Exception as e:
        logger.warning("Unexpected error for %s: %s", url, e)
    return None


def get_coingecko_id(symbol: str) -> str:
    """Resolve a ticker symbol to a CoinGecko coin ID."""
    return SYMBOL_TO_CG_ID.get(symbol.upper(), symbol.lower())


# ─── CoinGecko ────────────────────────────────────────────────────────────────


def fetch_coinbase_spot_price(symbol: str) -> Optional[float]:
    """Fetch spot price from Coinbase v2 API. Simple, free, no auth needed."""
    data = _get(f"https://api.coinbase.com/v2/prices/{symbol.upper()}-USD/spot")
    if data and "data" in data:
        try:
            return float(data["data"]["amount"])
        except (KeyError, ValueError, TypeError):
            pass
    return None


def fetch_coingecko_price(symbol: str) -> Dict[str, Any]:
    """
    Fetch current price, market data, and 7-day sparkline from CoinGecko.
    Falls back to Coinbase v2 spot price if CoinGecko is unavailable or rate-limited.
    Returns a flat dict with 'error' key set if anything fails.
    """
    coin_id = get_coingecko_id(symbol)
    data = _get(
        f"{COINGECKO_BASE}/coins/{coin_id}",
        {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "true",
        },
    )

    # CoinGecko failed — try Coinbase v2 spot as price-only fallback
    if not data or (isinstance(data, dict) and data.get("_rate_limited")):
        cb_price = fetch_coinbase_spot_price(symbol)
        result = {"symbol": symbol.upper(), "_rate_limited": bool(data and data.get("_rate_limited"))}
        if cb_price:
            result["price"] = cb_price
            result["_price_source"] = "coinbase"
            logger.info("Using Coinbase spot price fallback for %s: $%.4f", symbol, cb_price)
        else:
            result["error"] = "CoinGecko and Coinbase both unavailable"
        return result

    md = data.get("market_data", {})
    usd = lambda key: (md.get(key) or {}).get("usd")

    return {
        "symbol": symbol.upper(),
        "name": data.get("name", symbol),
        "price": usd("current_price"),
        "market_cap": usd("market_cap"),
        "volume_24h": usd("total_volume"),
        "change_24h": md.get("price_change_percentage_24h"),
        "change_7d": md.get("price_change_percentage_7d"),
        "change_30d": md.get("price_change_percentage_30d"),
        "high_24h": usd("high_24h"),
        "low_24h": usd("low_24h"),
        "ath": usd("ath"),
        "ath_change_pct": (md.get("ath_change_percentage") or {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
        "market_cap_rank": data.get("market_cap_rank"),
        "sparkline_7d": (md.get("sparkline_7d") or {}).get("price", []),
    }


# ─── Binance ──────────────────────────────────────────────────────────────────

# Cache of symbols known NOT to exist on Binance.US (avoids repeated 400s)
_binance_missing: set = set()


def _binance_has_pair(symbol: str) -> bool:
    """Check if a USDT pair exists on Binance.US. Caches misses."""
    pair = f"{symbol.upper()}USDT"
    if pair in _binance_missing:
        return False
    data = _get(f"{BINANCE_BASE}/ticker/price", {"symbol": pair})
    if not data:
        _binance_missing.add(pair)
        logger.debug("%s not available on Binance.US — will use Coinbase", pair)
        return False
    return True


def fetch_binance_ohlcv(
    symbol: str,
    interval: str = "1h",
    limit: int = 200,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV candles from Binance public klines endpoint.
    interval: 1m, 5m, 15m, 1h, 4h, 1d
    Returns a DataFrame indexed by UTC timestamp, or None on failure.
    """
    pair = f"{symbol.upper()}USDT"
    if pair in _binance_missing:
        return None
    raw = _get(
        f"{BINANCE_BASE}/klines",
        {"symbol": pair, "interval": interval, "limit": limit},
    )
    if not raw:
        return None

    df = pd.DataFrame(
        raw,
        columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("timestamp", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_binance_ohlcv_multi(symbol: str) -> Dict[str, Optional[pd.DataFrame]]:
    """Fetch OHLCV for 15m, 1h, 4h, and 1d timeframes."""
    # Skip Binance entirely if the pair doesn't exist
    if not _binance_has_pair(symbol):
        return {"15m": None, "1h": None, "4h": None, "1d": None}
    timeframes = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    results: Dict[str, Optional[pd.DataFrame]] = {}
    for name, interval in timeframes.items():
        results[name] = fetch_binance_ohlcv(symbol, interval=interval, limit=200)
        time.sleep(0.08)  # gentle rate-limit courtesy
    return results


def fetch_binance_funding_rate(symbol: str) -> Optional[float]:
    """
    Binance.US does not provide a perpetual futures API, so funding rate data
    is unavailable via this data source. Returns None gracefully.
    """
    logger.debug("Funding rate skipped — Binance.US has no futures/perpetuals API.")
    return None


def fetch_binance_order_book(symbol: str, limit: int = 20) -> Optional[Dict]:
    """Fetch a depth snapshot from Binance."""
    pair = f"{symbol.upper()}USDT"
    if pair in _binance_missing:
        return None
    return _get(f"{BINANCE_BASE}/depth", {"symbol": pair, "limit": limit})


def compute_order_book_imbalance(ob: Dict) -> Optional[float]:
    """
    Compute bid/ask volume imbalance as a percentage.
    Positive = more bid volume (buy pressure), negative = more ask volume.
    """
    if not ob:
        return None
    try:
        bids = sum(float(b[1]) for b in ob.get("bids", []))
        asks = sum(float(a[1]) for a in ob.get("asks", []))
        total = bids + asks
        return round((bids - asks) / total * 100, 1) if total > 0 else 0.0
    except Exception:
        return None


# ─── Coinbase Advanced Trade API ─────────────────────────────────────────────
# Public endpoints work without auth. With a CDP API key, you get 3x rate limits
# (30/sec vs 10/sec) and access to authenticated endpoints like best_bid_ask.


# Coinbase candle granularity: interval -> (API enum string, seconds per candle)
_CB_GRANULARITY = {
    "15m": ("FIFTEEN_MINUTE", 900),
    "1h":  ("ONE_HOUR", 3600),
    "4h":  ("SIX_HOUR", 21600),   # Coinbase has 6H, closest to 4H
    "1d":  ("ONE_DAY", 86400),
}


def _coinbase_get(url: str, params: dict = None, authenticated: bool = False) -> Optional[dict]:
    """GET with optional Coinbase auth. Public endpoints don't need auth."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path  # e.g. /api/v3/brokerage/best_bid_ask

        if authenticated and coinbase_authenticated():
            headers = _coinbase_auth_headers("GET", path)
        else:
            headers = {"Content-Type": "application/json"}

        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning("Coinbase rate limited (429) for %s", url)
        else:
            logger.warning("Coinbase HTTP error %s for %s", e, url)
    except Exception as e:
        logger.warning("Coinbase request failed for %s: %s", url, e)
    return None


def fetch_coinbase_ohlcv(
    symbol: str,
    interval: str = "1h",
    limit: int = 200,
) -> Optional[pd.DataFrame]:
    """Fetch OHLCV candles from Coinbase. Uses auth headers if configured."""
    product_id = f"{symbol.upper()}-USD"
    gran = _CB_GRANULARITY.get(interval)
    if gran is None:
        logger.warning("Coinbase: unsupported interval %s", interval)
        return None

    gran_enum, secs_per_candle = gran

    # Coinbase returns max 300 candles; compute start/end window
    end = int(time.time())
    start = end - (min(limit, 300) * secs_per_candle)

    raw = _coinbase_get(
        f"{COINBASE_BASE}/products/{product_id}/candles",
        {"start": str(start), "end": str(end), "granularity": gran_enum},
    )
    if not raw or not isinstance(raw, dict):
        return None

    candles = raw.get("candles", [])
    if not candles:
        return None

    df = pd.DataFrame(candles)
    # Coinbase returns: start (unix), low, high, open, close, volume
    df["start"] = pd.to_numeric(df["start"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["start"], unit="s", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_coinbase_ticker(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch best bid/ask and recent trades from Coinbase."""
    product_id = f"{symbol.upper()}-USD"

    # Try authenticated best_bid_ask first (more reliable), fall back to public ticker
    if coinbase_authenticated():
        raw = _coinbase_get(
            f"{COINBASE_AUTH_BASE}/best_bid_ask",
            {"product_ids": product_id},
            authenticated=True,
        )
        if raw and isinstance(raw, dict):
            pricebooks = raw.get("pricebooks", [])
            if pricebooks:
                pb = pricebooks[0]
                bids = pb.get("bids", [])
                asks = pb.get("asks", [])
                result: Dict[str, Any] = {"authenticated": True}
                if bids:
                    result["best_bid"] = float(bids[0].get("price", 0))
                if asks:
                    result["best_ask"] = float(asks[0].get("price", 0))
                if result.get("best_bid") and result.get("best_ask"):
                    mid = (result["best_bid"] + result["best_ask"]) / 2
                    result["spread_pct"] = round(
                        (result["best_ask"] - result["best_bid"]) / mid * 100, 4
                    ) if mid else None
                return result if len(result) > 1 else None

    # Public ticker fallback
    raw = _coinbase_get(f"{COINBASE_BASE}/products/{product_id}/ticker", {"limit": 1})
    if not raw or not isinstance(raw, dict):
        return None

    trades = raw.get("trades", [])
    best_bid = raw.get("best_bid")
    best_ask = raw.get("best_ask")

    result = {}
    if best_bid:
        result["best_bid"] = float(best_bid)
    if best_ask:
        result["best_ask"] = float(best_ask)
    if result.get("best_bid") and result.get("best_ask"):
        mid = (result["best_bid"] + result["best_ask"]) / 2
        result["spread_pct"] = round((result["best_ask"] - result["best_bid"]) / mid * 100, 4) if mid else None
    if trades:
        result["last_trade_price"] = float(trades[0].get("price", 0))
        result["last_trade_size"] = float(trades[0].get("size", 0))
        result["last_trade_side"] = trades[0].get("side", "")

    return result if result else None


def fetch_coinbase_order_book(symbol: str, limit: int = 20) -> Optional[Dict]:
    """Fetch order book depth from Coinbase."""
    product_id = f"{symbol.upper()}-USD"
    raw = _coinbase_get(
        f"{COINBASE_BASE}/product_book",
        {"product_id": product_id, "limit": str(limit)},
    )
    if not raw or not isinstance(raw, dict):
        return None

    pricebook = raw.get("pricebook", {})
    bids = pricebook.get("bids", [])
    asks = pricebook.get("asks", [])
    if not bids and not asks:
        return None

    # Normalize to same format as Binance: [[price, qty], ...]
    return {
        "bids": [[b.get("price", "0"), b.get("size", "0")] for b in bids],
        "asks": [[a.get("price", "0"), a.get("size", "0")] for a in asks],
        "source": "coinbase",
    }


# ─── Alternative.me Fear & Greed ──────────────────────────────────────────────


def fetch_fear_and_greed(days: int = 7) -> Dict[str, Any]:
    """
    Fetch Fear & Greed Index from alternative.me.
    Returns current value + history for trend analysis.
    """
    data = _get(f"{ALT_ME_BASE}/fng/", {"limit": days})
    if not data or "data" not in data:
        return {"value": 50, "classification": "Neutral", "error": "unavailable"}

    entries = data["data"]
    if not entries:
        return {"value": 50, "classification": "Neutral"}

    current = entries[0]
    return {
        "value": int(current.get("value", 50)),
        "classification": current.get("value_classification", "Neutral"),
        "timestamp": current.get("timestamp"),
        "history_7d": [
            {
                "value": int(e.get("value", 50)),
                "classification": e.get("value_classification", "Neutral"),
            }
            for e in entries
        ],
    }


# ─── yfinance fallback ─────────────────────────────────────────────────────────


def fetch_yfinance_ohlcv(
    symbol: str,
    period: str = "60d",
    interval: str = "1h",
) -> Optional[pd.DataFrame]:
    """
    Fallback OHLCV source via yfinance (Yahoo Finance).
    Uses <SYMBOL>-USD ticker format.
    """
    try:
        import yfinance as yf  # optional dependency

        ticker = yf.Ticker(f"{symbol.upper()}-USD")
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]].copy()
    except ImportError:
        logger.warning("yfinance not installed; skipping fallback")
    except Exception as e:
        logger.warning("yfinance error for %s: %s", symbol, e)
    return None


# ─── RSS news feed ────────────────────────────────────────────────────────────

import xml.etree.ElementTree as ET

_RSS_FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
]

_POSITIVE_WORDS = {
    "surge", "surges", "rally", "rallies", "bullish", "breakout", "gains",
    "gain", "rises", "rose", "soars", "soar", "high", "record", "adoption",
    "approval", "approve", "approved", "launch", "launches", "partnership",
    "upgrade", "upgrades", "buy", "accumulate", "outperform",
}
_NEGATIVE_WORDS = {
    "crash", "crashes", "drop", "drops", "plunge", "plunges", "bearish",
    "slump", "slumps", "fall", "falls", "fell", "ban", "banned", "hack",
    "hacked", "exploit", "exploited", "scam", "fraud", "sell", "dump",
    "dumps", "low", "loss", "losses", "lawsuit", "sec", "regulation",
    "restriction", "fear", "panic",
}


def _sentiment_from_title(title: str) -> str:
    words = set(title.lower().split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _fetch_rss(url: str) -> Optional[ET.Element]:
    """Fetch and parse an RSS feed; returns the root Element or None on failure."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return ET.fromstring(resp.content)
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", url, e)
        return None


def fetch_crypto_news(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch recent crypto headlines from free RSS feeds (CoinDesk, CoinTelegraph).
    Filters for items mentioning the coin symbol or its CoinGecko name.
    Returns up to 5 headline dicts with keys: title, source, published_at, sentiment.
    Returns an empty list on any failure.
    """
    from config import SYMBOL_TO_CG_ID  # local import to avoid circular issues

    sym_upper = symbol.upper()
    # Build a set of search terms: symbol + readable coin name tokens
    coin_id = SYMBOL_TO_CG_ID.get(sym_upper, sym_upper.lower())
    search_terms = {sym_upper.lower()} | {t for t in coin_id.replace("-", " ").split()}

    collected: List[Dict[str, Any]] = []

    for source_name, feed_url in _RSS_FEEDS:
        if len(collected) >= 5:
            break
        root = _fetch_rss(feed_url)
        if root is None:
            continue

        # RSS items are under channel/item; handle both with and without namespace
        items = root.findall(".//item")
        for item in items:
            if len(collected) >= 5:
                break

            title_el = item.find("title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            # Filter: headline must mention the coin
            title_lower = title.lower()
            if not any(term in title_lower for term in search_terms):
                continue

            pub_el = item.find("pubDate")
            pub_raw = (pub_el.text or "").strip() if pub_el is not None else ""
            # Normalise to YYYY-MM-DD where possible
            pub_date = pub_raw[:10] if pub_raw else ""
            try:
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(pub_raw).strftime("%Y-%m-%d")
            except Exception:
                pass

            collected.append({
                "title": title,
                "source": source_name,
                "published_at": pub_date,
                "sentiment": _sentiment_from_title(title),
            })

    if not collected:
        logger.info("No RSS headlines found for %s", symbol)
    return collected


# ─── Deribit Options ─────────────────────────────────────────────────────────


def fetch_deribit_options(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch options data from Deribit public API (no auth needed).
    Calculates put/call ratio from book summaries.
    Only BTC and ETH are supported; returns None for other symbols.
    """
    sym = symbol.upper()
    if sym not in ("BTC", "ETH"):
        logger.debug("Deribit options only supports BTC/ETH, skipping %s", sym)
        return None

    try:
        # Fetch option book summaries
        summary_url = (
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        )
        data = _get(summary_url, {"currency": sym, "kind": "option"})
        if not data or "result" not in data:
            logger.warning("Deribit book summary unavailable for %s", sym)
            return None

        instruments = data["result"]
        total_put_volume = 0.0
        total_call_volume = 0.0

        for inst in instruments:
            name = inst.get("instrument_name", "")
            vol = float(inst.get("volume", 0) or 0)
            if "-P" in name:
                total_put_volume += vol
            elif "-C" in name:
                total_call_volume += vol

        put_call_ratio = (
            round(total_put_volume / total_call_volume, 4)
            if total_call_volume > 0
            else 0.0
        )

        # Fetch current index price
        index_url = "https://www.deribit.com/api/v2/public/get_index_price"
        index_data = _get(index_url, {"index_name": f"{sym.lower()}_usd"})
        index_price = None
        if index_data and "result" in index_data:
            index_price = index_data["result"].get("index_price")

        return {
            "put_call_ratio": put_call_ratio,
            "total_put_volume": total_put_volume,
            "total_call_volume": total_call_volume,
            "max_pain": None,
            "iv_index": None,
            "index_price": index_price,
        }
    except Exception as e:
        logger.warning("Deribit options fetch failed for %s: %s", sym, e)
        return None


# ─── CoinGlass Futures / Open Interest ───────────────────────────────────────


def fetch_coinglass_futures(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch futures open interest data from CoinGlass public API.
    Returns OI in USD and 24h change percentage, or None on failure.
    """
    sym = symbol.upper()
    try:
        url = "https://open-api.coinglass.com/public/v2/open_interest"
        resp = requests.get(
            url,
            params={"symbol": sym, "interval": "0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0 or not data.get("data"):
            logger.info("CoinGlass returned no OI data for %s", sym)
            return None

        oi_list = data["data"]
        # Sum open interest across all exchanges
        total_oi = sum(float(ex.get("openInterest", 0) or 0) for ex in oi_list)
        # Average 24h change across exchanges (where available)
        changes = [
            float(ex["h24Change"])
            for ex in oi_list
            if ex.get("h24Change") is not None
        ]
        avg_change = round(sum(changes) / len(changes), 2) if changes else 0.0

        return {
            "open_interest_usd": total_oi,
            "oi_change_24h_pct": avg_change,
        }
    except Exception as e:
        logger.warning("CoinGlass futures fetch failed for %s: %s", sym, e)
        return None


# ─── On-chain Data ───────────────────────────────────────────────────────────


def fetch_onchain_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch on-chain metrics from free public APIs.
    BTC: hash rate and difficulty from Blockchain.com.
    ETH: placeholder for Etherscan (requires ETHERSCAN_API_KEY).
    All: MVRV from Glassnode (requires GLASSNODE_API_KEY).
    Returns None if no data can be retrieved.
    """
    sym = symbol.upper()
    result: Dict[str, Any] = {
        "exchange_netflow": None,
        "mvrv": None,
        "nupl": None,
        "hashrate": None,
    }

    try:
        # BTC-specific: blockchain.com stats
        if sym == "BTC":
            stats = _get("https://api.blockchain.info/stats")
            if stats:
                result["hashrate"] = stats.get("hash_rate")
                result["difficulty"] = stats.get("difficulty")

        # ETH-specific: Etherscan (if key available)
        if sym == "ETH":
            etherscan_key = os.environ.get("ETHERSCAN_API_KEY", "")
            if etherscan_key:
                eth_data = _get(
                    "https://api.etherscan.io/api",
                    {
                        "module": "stats",
                        "action": "ethprice",
                        "apikey": etherscan_key,
                    },
                )
                if eth_data and eth_data.get("status") == "1":
                    eth_result = eth_data.get("result", {})
                    result["eth_price_usd"] = eth_result.get("ethusd")

        # Glassnode MVRV (if key available)
        glassnode_key = os.environ.get("GLASSNODE_API_KEY", "")
        if glassnode_key and sym in ("BTC", "ETH"):
            asset_map = {"BTC": "BTC", "ETH": "ETH"}
            mvrv_data = _get(
                "https://api.glassnode.com/v1/metrics/market/mvrv",
                {"a": asset_map[sym], "api_key": glassnode_key, "s": "0", "i": "24h"},
            )
            if mvrv_data and isinstance(mvrv_data, list) and mvrv_data:
                result["mvrv"] = mvrv_data[-1].get("v")

        # Return None if we got absolutely nothing useful
        has_data = any(v is not None for v in result.values())
        return result if has_data else None
    except Exception as e:
        logger.warning("On-chain data fetch failed for %s: %s", sym, e)
        return None


# ─── DeFi Data (DeFiLlama) ──────────────────────────────────────────────────

# Mapping of token symbols to DeFiLlama protocol slugs
_SYMBOL_TO_DEFI_PROTOCOL: Dict[str, str] = {
    # ETH is a chain token, not a protocol — handled by _CHAIN_TOKENS below
    "UNI": "uniswap",
    "AAVE": "aave",
    "MKR": "makerdao",
    "CRV": "curve-finance",
    "LDO": "lido",
    "SUSHI": "sushi",
    "COMP": "compound-finance",
    "SNX": "synthetix",
    "YFI": "yearn-finance",
    "DYDX": "dydx",
    "GMX": "gmx",
    "PENDLE": "pendle",
}

# Symbols that are chain tokens (use chain TVL endpoint)
_CHAIN_TOKENS: Dict[str, str] = {
    "ETH": "Ethereum",
    "BNB": "BSC",
    "AVAX": "Avalanche",
    "SOL": "Solana",
    "MATIC": "Polygon",
    "FTM": "Fantom",
    "ARB": "Arbitrum",
    "OP": "Optimism",
}


def fetch_defi_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch DeFi metrics from DeFiLlama (free, no auth required).
    Retrieves TVL and TVL changes for protocols or chain tokens.
    Returns None if the symbol has no known DeFi mapping.
    """
    sym = symbol.upper()

    try:
        # Try protocol-level TVL first
        protocol_slug = _SYMBOL_TO_DEFI_PROTOCOL.get(sym)
        if protocol_slug:
            data = _get(f"https://api.llama.fi/protocol/{protocol_slug}")
            if data and isinstance(data, dict):
                tvl = data.get("currentChainTvls", {})
                total_tvl = sum(
                    float(v) for v in tvl.values() if isinstance(v, (int, float))
                )
                if total_tvl == 0:
                    total_tvl = float(data.get("tvl", 0) or 0)

                # Calculate TVL changes from historical data
                tvl_change_24h = None
                tvl_change_7d = None
                tvl_history = data.get("tvl", [])
                if isinstance(tvl_history, list) and len(tvl_history) >= 2:
                    current_tvl = tvl_history[-1].get("totalLiquidityUSD", 0)
                    if len(tvl_history) >= 2:
                        prev_tvl = tvl_history[-2].get("totalLiquidityUSD", 0)
                        if prev_tvl > 0:
                            tvl_change_24h = round(
                                (current_tvl - prev_tvl) / prev_tvl * 100, 2
                            )
                    if len(tvl_history) >= 8:
                        week_ago_tvl = tvl_history[-8].get("totalLiquidityUSD", 0)
                        if week_ago_tvl > 0:
                            tvl_change_7d = round(
                                (current_tvl - week_ago_tvl) / week_ago_tvl * 100, 2
                            )

                return {
                    "tvl": total_tvl,
                    "tvl_change_24h": tvl_change_24h,
                    "tvl_change_7d": tvl_change_7d,
                }

        # Try chain-level TVL
        chain_name = _CHAIN_TOKENS.get(sym)
        if chain_name:
            chains_data = _get("https://api.llama.fi/v2/chains")
            if chains_data and isinstance(chains_data, list):
                for chain in chains_data:
                    if chain.get("name") == chain_name:
                        return {
                            "tvl": float(chain.get("tvl", 0) or 0),
                            "tvl_change_24h": None,
                            "tvl_change_7d": None,
                        }

        logger.debug("No DeFiLlama mapping for %s", sym)
        return None
    except Exception as e:
        logger.warning("DeFi data fetch failed for %s: %s", sym, e)
        return None


# ─── ETF Flows ───────────────────────────────────────────────────────────────


def fetch_etf_flows(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch ETF flow data for BTC and ETH.
    Currently a stub — reliable free ETF flow APIs are not publicly available.
    Returns a structured dict with None values for future integration.
    """
    sym = symbol.upper()
    if sym not in ("BTC", "ETH"):
        return None

    return {
        "daily_flow_usd": None,
        "weekly_flow_usd": None,
        "total_aum": None,
    }


# ─── Master fetch ─────────────────────────────────────────────────────────────


def fetch_all_market_data(symbol: str) -> Dict[str, Any]:
    """
    Aggregate all available free market data for a symbol.

    Returns:
        {
          'symbol': str,
          'coingecko': {...},
          'ohlcv': {'15m': df, '1h': df, '4h': df, '1d': df},
          'funding_rate': float | None,
          'fear_greed': {...},
          'order_book_imbalance': float | None,
          'coinbase_ticker': {...} | None,
          'options': {...} | None,      # Deribit options (BTC/ETH)
          'futures': {...} | None,      # CoinGlass open interest
          'onchain': {...} | None,      # On-chain metrics
          'defi': {...} | None,         # DeFiLlama TVL data
          'etf_flows': {...} | None,    # ETF flow data (stub)
        }
    """
    symbol = symbol.upper()
    result: Dict[str, Any] = {
        "symbol": symbol,
        "coingecko": {},
        "ohlcv": {},
        "funding_rate": None,
        "fear_greed": {},
        "order_book_imbalance": None,
        "coinbase_ticker": None,
        "options": None,
        "futures": None,
        "onchain": None,
        "defi": None,
        "etf_flows": None,
    }

    # CoinGecko (handles 429 internally — returns {'_rate_limited': True} if still failing)
    result["coingecko"] = fetch_coingecko_price(symbol)
    if result["coingecko"].get("_rate_limited"):
        result["_cg_rate_limited"] = True

    # Binance OHLCV (multi-timeframe)
    ohlcv_data = fetch_binance_ohlcv_multi(symbol)

    # Fallback chain: Binance → Coinbase → yfinance
    # yfinance does not support 4H natively, but Coinbase does (as 6H granularity).
    YF_INTERVAL_MAP = {"15m": "15m", "1h": "1h", "1d": "1d"}
    for tf, df in ohlcv_data.items():
        if df is not None and not df.empty:
            continue
        # Try Coinbase first (supports 15m, 1h, 4h, 1d)
        cb_fallback = fetch_coinbase_ohlcv(symbol, interval=tf, limit=200)
        if cb_fallback is not None and not cb_fallback.empty:
            logger.info("Using Coinbase OHLCV fallback for %s/%s", symbol, tf)
            ohlcv_data[tf] = cb_fallback
            continue
        # Then try yfinance (no 4H support)
        yf_interval = YF_INTERVAL_MAP.get(tf)
        if yf_interval:
            yf_fallback = fetch_yfinance_ohlcv(symbol, period="60d", interval=yf_interval)
            if yf_fallback is not None and not yf_fallback.empty:
                logger.info("Using yfinance OHLCV fallback for %s/%s", symbol, tf)
                ohlcv_data[tf] = yf_fallback
                continue
        logger.warning("%s OHLCV unavailable for %s from all sources", tf.upper(), symbol)
        ohlcv_data[tf] = None
    result["ohlcv"] = ohlcv_data

    # Coinbase ticker (bid/ask spread — useful for MARCUS tape-reading context)
    result["coinbase_ticker"] = fetch_coinbase_ticker(symbol)

    # Funding rate (perpetual futures)
    result["funding_rate"] = fetch_binance_funding_rate(symbol)

    # Fear & Greed
    result["fear_greed"] = fetch_fear_and_greed(days=7)

    # Order book imbalance — try Binance first, fall back to Coinbase
    ob = fetch_binance_order_book(symbol, limit=20)
    if not ob:
        ob = fetch_coinbase_order_book(symbol, limit=20)
    result["order_book_imbalance"] = compute_order_book_imbalance(ob)

    # Recent news headlines (for NOVA's macro context)
    result["news"] = fetch_crypto_news(symbol)

    # Options data from Deribit (BTC/ETH only)
    result["options"] = fetch_deribit_options(symbol)

    # Futures / open interest from CoinGlass
    result["futures"] = fetch_coinglass_futures(symbol)

    # On-chain metrics (hash rate, MVRV, etc.)
    result["onchain"] = fetch_onchain_data(symbol)

    # DeFi TVL data from DeFiLlama
    result["defi"] = fetch_defi_data(symbol)

    # ETF flow data (BTC/ETH only — stub for now)
    result["etf_flows"] = fetch_etf_flows(symbol)

    return result
