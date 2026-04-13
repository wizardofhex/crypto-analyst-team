"""
config.py — Shared constants for the Crypto Analyst Team.
All modules should import from here to avoid duplication and drift.
"""

from pathlib import Path

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "recommendations.db"

# ─── Analysts ─────────────────────────────────────────────────────────────────
ANALYST_ORDER = [
    "ARIA", "MARCUS", "NOVA", "VEGA", "DELTA", "CHAIN",
    "QUANT", "DEFI", "ATLAS", "REX", "ZEN",
]

# ─── Portfolio ─────────────────────────────────────────────────────────────────
PORTFOLIO_SIZE = 124_000  # USD — update here to change sizing across the whole app

# ─── CoinGecko ────────────────────────────────────────────────────────────────
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

SYMBOL_TO_CG_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "OP": "optimism",
    "ARB": "arbitrum",
    "SUI": "sui",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "PEPE": "pepe",
    "WIF": "dogwifhat",
    "BONK": "bonk",
    "TON": "the-open-network",
    "SHIB": "shiba-inu",
    "FET": "fetch-ai",
    "RENDER": "render-token",
    "IMX": "immutable-x",
    "SEI": "sei-network",
    "HBAR": "hedera-hashgraph",
    "RPL": "rocket-pool",
}
