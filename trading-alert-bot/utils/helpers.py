"""Shared formatting and classification utilities."""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Asset-class classification
# ---------------------------------------------------------------------------

FOREX_CURRENCIES = {
    "EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SEK", "NOK",
    "DKK", "SGD", "HKD", "TRY", "ZAR", "MXN", "PLN", "CZK", "HUF",
}

COMMODITY_KEYWORDS = {
    "XAU", "XAG", "GOLD", "SILVER", "BRENT", "WTI", "OIL", "NATGAS",
    "NGAS", "COPPER", "WHEAT", "CORN", "SOYBEAN", "PLATINUM", "PALLADIUM",
}

INDEX_KEYWORDS = {
    "US30", "SPX500", "SPX", "NAS100", "NASDAQ", "UK100", "FTSE",
    "GER40", "DAX", "JPN225", "NIKKEI", "AUS200", "FRA40", "EU50",
    "US500", "US100", "US2000", "HK50", "CHINA50",
}

CRYPTO_QUOTES = {"USDT", "BTC", "ETH", "BNB", "BUSD", "USDC", "USD"}


def classify_asset(symbol: str, exchange: str = "") -> str:
    """Return one of: crypto, forex, commodity, index, stock."""
    sym = symbol.upper().replace("/", "").replace("-", "").replace("_", "")

    # Indices
    for kw in INDEX_KEYWORDS:
        if kw in sym:
            return "index"

    # Commodities
    for kw in COMMODITY_KEYWORDS:
        if kw in sym:
            return "commodity"

    # Forex — both parts are fiat currencies
    parts = _split_pair(symbol)
    if parts and all(p in FOREX_CURRENCIES for p in parts):
        return "forex"

    # Binance symbols are overwhelmingly crypto
    if exchange.lower() in ("binance",):
        return "crypto"

    # Markets.com crypto CFDs
    if parts and any(p in CRYPTO_QUOTES for p in parts):
        return "crypto"

    # Default for Markets.com non-crypto
    if exchange.lower() in ("markets.com", "markets_com", "yfinance"):
        return "stock"

    return "crypto"


def _split_pair(symbol: str) -> Optional[list[str]]:
    """Try to split a trading pair into [base, quote]."""
    if "/" in symbol:
        return [p.strip().upper() for p in symbol.split("/")]
    if "_" in symbol:
        return [p.strip().upper() for p in symbol.split("_")]
    # Try common 3-char splits for 6-char symbols like EURUSD
    clean = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    if len(clean) == 6:
        return [clean[:3], clean[3:]]
    if len(clean) == 7:
        return [clean[:4], clean[4:]]
    return None


# ---------------------------------------------------------------------------
# Decimal formatting per asset class
# ---------------------------------------------------------------------------

def format_price(price: float, asset_class: str, symbol: str = "") -> str:
    """Format price with appropriate decimal places for the asset class."""
    if asset_class == "forex":
        # JPY pairs use 3 decimals, others use 5
        if "JPY" in symbol.upper():
            return f"{price:.3f}"
        return f"{price:.5f}"
    elif asset_class == "crypto":
        if price >= 1000:
            return f"{price:.2f}"
        elif price >= 1:
            return f"{price:.4f}"
        elif price >= 0.01:
            return f"{price:.6f}"
        else:
            return f"{price:.8f}"
    else:
        # Commodities, indices, stocks
        return f"{price:.2f}"


def pct_change(entry: float, target: float) -> str:
    """Return signed percentage string like '+2.35%' or '-1.20%'."""
    if entry == 0:
        return "0.00%"
    change = ((target - entry) / entry) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"


def progress_bar(value: float, max_val: float = 100, width: int = 10) -> str:
    """Build a Unicode progress bar: █ filled, ░ empty."""
    ratio = max(0.0, min(1.0, value / max_val)) if max_val else 0
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Symbol keyword mapping (for news → symbol matching)
# ---------------------------------------------------------------------------

SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth", "ether"],
    "BNB": ["binance coin", "bnb"],
    "XRP": ["ripple", "xrp"],
    "SOL": ["solana", "sol"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"],
    "DOT": ["polkadot", "dot"],
    "AVAX": ["avalanche", "avax"],
    "MATIC": ["polygon", "matic"],
    "LINK": ["chainlink", "link"],
    "XAU": ["gold", "xau"],
    "XAG": ["silver", "xag"],
    "WTI": ["crude oil", "wti", "oil price"],
    "BRENT": ["brent", "brent oil"],
    "NATGAS": ["natural gas", "natgas"],
    "EUR/USD": ["euro", "eur/usd", "eurusd"],
    "GBP/USD": ["pound", "sterling", "gbp/usd", "gbpusd"],
    "USD/JPY": ["yen", "usd/jpy", "usdjpy"],
    "AAPL": ["apple", "aapl"],
    "TSLA": ["tesla", "tsla"],
    "NVDA": ["nvidia", "nvda"],
    "AMZN": ["amazon", "amzn"],
    "MSFT": ["microsoft", "msft"],
    "GOOGL": ["google", "alphabet", "googl"],
    "META": ["meta", "facebook"],
    "US30": ["dow jones", "dow", "us30", "djia"],
    "SPX500": ["s&p 500", "s&p", "spx", "sp500"],
    "NAS100": ["nasdaq", "nas100", "ndx"],
    "UK100": ["ftse", "uk100"],
    "GER40": ["dax", "ger40", "german"],
    "JPN225": ["nikkei", "jpn225", "japan"],
}
