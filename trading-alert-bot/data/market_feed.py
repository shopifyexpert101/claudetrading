"""Unified data layer wrapping Binance and Markets.com feeds."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import pandas as pd

from data.binance_feed import BinanceFeed
from data.markets_feed import MarketsFeed
from utils.helpers import classify_asset

logger = logging.getLogger("trading_bot")


class UnifiedMarketFeed:
    """Unified interface for all exchange data feeds."""

    def __init__(self, config: dict, env: dict):
        self.config = config
        binance_cfg = config.get("exchanges", {}).get("binance", {})
        markets_cfg = config.get("exchanges", {}).get("markets_com", {})

        self.binance: Optional[BinanceFeed] = None
        self.markets: Optional[MarketsFeed] = None

        if binance_cfg.get("enabled", False):
            self.binance = BinanceFeed(
                binance_cfg,
                api_key=env.get("BINANCE_API_KEY", ""),
                api_secret=env.get("BINANCE_API_SECRET", ""),
            )

        if markets_cfg.get("enabled", False):
            self.markets = MarketsFeed(
                markets_cfg,
                api_key=env.get("MARKETS_COM_API_KEY", ""),
                api_secret=env.get("MARKETS_COM_API_SECRET", ""),
                account_id=env.get("MARKETS_COM_ACCOUNT_ID", ""),
            )

        # All discovered symbols: symbol -> {exchange, asset_class, ...}
        self.all_symbols: dict[str, dict] = {}
        self._candle_callback: Optional[Callable] = None

    async def discover_all(self, single_asset: str = "") -> dict[str, dict]:
        """Discover symbols from all enabled exchanges."""
        tasks = []
        if self.binance:
            tasks.append(("binance", self.binance.discover_symbols()))
        if self.markets:
            tasks.append(("markets", self.markets.discover_symbols()))

        results = await asyncio.gather(
            *[t[1] for t in tasks], return_exceptions=True
        )

        for i, (name, _) in enumerate(tasks):
            result = results[i]
            if isinstance(result, Exception):
                logger.error("%s discovery failed: %s", name, result)
                continue
            for sym, info in result.items():
                info["asset_class"] = classify_asset(sym, info.get("exchange", name))
                self.all_symbols[sym] = info

        # Filter to single asset if specified
        if single_asset:
            filtered = {}
            for sym, info in self.all_symbols.items():
                if single_asset.upper() in sym.upper().replace("/", ""):
                    filtered[sym] = info
            if filtered:
                self.all_symbols = filtered
                logger.info("Filtered to %d symbols matching '%s'", len(filtered), single_asset)
            else:
                logger.warning("No symbols matching '%s' found", single_asset)

        # Log summary
        by_exchange: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for info in self.all_symbols.values():
            ex = info.get("exchange", "unknown")
            ac = info.get("asset_class", "unknown")
            by_exchange[ex] = by_exchange.get(ex, 0) + 1
            by_class[ac] = by_class.get(ac, 0) + 1

        logger.info("Total symbols discovered: %d", len(self.all_symbols))
        for ex, count in by_exchange.items():
            logger.info("  %s: %d symbols", ex, count)
        for ac, count in by_class.items():
            logger.info("  %s: %d instruments", ac, count)

        return self.all_symbols

    async def fetch_history(self, symbol: str, timeframe: str = "5m",
                            limit: int = 200) -> pd.DataFrame:
        """Fetch OHLCV history for a symbol from the appropriate feed."""
        info = self.all_symbols.get(symbol, {})
        exchange = info.get("exchange", "")

        if exchange == "binance" and self.binance:
            return await self.binance.fetch_ohlcv(symbol, timeframe, limit)
        elif self.markets:
            return await self.markets.fetch_ohlcv(symbol, timeframe, limit)
        return pd.DataFrame()

    def get_candle_buffer(self, symbol: str) -> pd.DataFrame:
        """Get the current candle buffer for a symbol."""
        info = self.all_symbols.get(symbol, {})
        exchange = info.get("exchange", "")

        if exchange == "binance" and self.binance:
            return self.binance.candle_buffers.get(symbol, pd.DataFrame())
        elif self.markets:
            return self.markets.candle_buffers.get(symbol, pd.DataFrame())
        return pd.DataFrame()

    def set_candle_callback(self, callback: Callable):
        """Set unified candle callback."""
        self._candle_callback = callback
        if self.binance:
            self.binance.set_candle_callback(callback)
        if self.markets:
            self.markets.set_candle_callback(callback)

    async def start(self):
        """Start all data feeds."""
        tasks = []
        if self.binance and self.binance.symbols:
            # Pre-fetch history for all Binance symbols
            timeframe = self.config.get("exchanges", {}).get("binance", {}).get("timeframe", "5m")
            for sym in list(self.binance.symbols.keys()):
                try:
                    await self.binance.fetch_ohlcv(sym, timeframe)
                except Exception as e:
                    logger.error("Pre-fetch error for %s: %s", sym, e)
            tasks.append(self.binance.start_websockets())

        if self.markets and self.markets.symbols:
            # Pre-fetch history for Markets.com symbols
            timeframe = self.config.get("exchanges", {}).get("markets_com", {}).get("timeframe", "5m")
            for sym in list(self.markets.symbols.keys()):
                try:
                    await self.markets.fetch_ohlcv(sym, timeframe)
                except Exception as e:
                    logger.error("Pre-fetch error for %s: %s", sym, e)
            tasks.append(self.markets.start_polling())

        if tasks:
            await asyncio.gather(*tasks)

    async def stop(self):
        """Stop all data feeds."""
        tasks = []
        if self.binance:
            tasks.append(self.binance.stop())
        if self.markets:
            tasks.append(self.markets.stop())
        if tasks:
            await asyncio.gather(*tasks)
        logger.info("All feeds stopped")
