"""Markets.com data feed — REST polling with yfinance fallback."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import aiohttp
import pandas as pd

logger = logging.getLogger("trading_bot")

# Default Markets.com instruments to track if discovery fails
DEFAULT_INSTRUMENTS = {
    # Forex
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X", "GBP/JPY": "GBPJPY=X", "EUR/GBP": "EURGBP=X",
    "USD/CAD": "USDCAD=X", "NZD/USD": "NZDUSD=X", "USD/CHF": "USDCHF=X",
    # Commodities
    "XAG/USD": "SI=F", "NATGAS": "NG=F", "COPPER": "HG=F",
    # Indices
    "US30": "YM=F", "SPX500": "ES=F", "NAS100": "NQ=F",
    "UK100": "^FTSE", "GER40": "^GDAXI", "JPN225": "^N225",
    "AUS200": "^AXJO",
    # Stocks — Geopolitically Insulated
    # Utilities
    "NEE": "NEE", "AEP": "AEP", "ED": "ED", "AWK": "AWK", "MGE": "MGE",
    # Waste Management
    "WM": "WM", "RSG": "RSG", "CWST": "CWST",
    # Death Care
    "SCI": "SCI", "CSV": "CSV",
    # Healthcare — Domestic Providers
    "HCA": "HCA", "UHS": "UHS", "ACHC": "ACHC",
    # Consumer Staples — Domestic
    "KR": "KR", "SFM": "SFM",
    # Domestic REITs
    "EXR": "EXR", "NHI": "NHI",
    # Domestic Telecom & Infrastructure
    "ATUS": "ATUS",
    # Services
    "IAA": "IAA",
    # Domestic HVAC/Mechanical Services
    "CNS": "CNS",
    # Crypto CFDs
    "BTC/USD": "BTC-USD", "ETH/USD": "ETH-USD",
}


class MarketsFeed:
    """Markets.com REST API polling with yfinance fallback."""

    MARKETS_COM_BASE = "https://api.markets.com/v1"

    def __init__(self, config: dict, api_key: str = "", api_secret: str = "",
                 account_id: str = ""):
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_id = account_id
        self.poll_interval = config.get("poll_interval_sec", 12600)
        self.symbols: dict[str, dict] = {}
        self.candle_buffers: dict[str, pd.DataFrame] = {}
        self._running = False
        self._candle_callback: Optional[Callable] = None
        self._use_yfinance = False
        self._poll_task: Optional[asyncio.Task] = None
        self._yf = None  # Lazy-loaded yfinance module

    async def discover_symbols(self) -> dict[str, dict]:
        """Discover available instruments from Markets.com API."""
        if not self.api_key:
            logger.warning(
                "Markets.com API key not configured. "
                "Set MARKETS_COM_API_KEY in .env. Falling back to yfinance."
            )
            return await self._fallback_yfinance_discover()

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                async with session.get(
                    f"{self.MARKETS_COM_BASE}/instruments",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        instruments = data.get("instruments", data.get("data", []))
                        for inst in instruments:
                            sym = inst.get("symbol", inst.get("name", ""))
                            if not sym:
                                continue
                            self.symbols[sym] = {
                                "exchange": "markets.com",
                                "instrument_id": inst.get("id", sym),
                                "asset_class": inst.get("category", "unknown"),
                                "last_price": inst.get("bid", 0),
                            }
                        logger.info("Markets.com: discovered %d instruments", len(self.symbols))
                        return self.symbols
                    elif resp.status in (401, 403):
                        logger.error(
                            "Markets.com auth failed (HTTP %d). "
                            "Check MARKETS_COM_API_KEY and MARKETS_COM_API_SECRET in .env. "
                            "The API uses cTrader Open API — see https://help.markets.com/en/articles/api",
                            resp.status,
                        )
                    elif resp.status == 404:
                        logger.error(
                            "Markets.com endpoint not found (HTTP 404). "
                            "The API structure may have changed. "
                            "Check https://help.markets.com/en/articles/api for current endpoints."
                        )
                    else:
                        logger.error("Markets.com API returned HTTP %d", resp.status)
        except aiohttp.ClientError as e:
            logger.error("Markets.com connection error: %s", e)
        except Exception as e:
            logger.error("Markets.com discovery error: %s", e)

        # Fallback
        if self.config.get("fallback_to_yfinance", True):
            return await self._fallback_yfinance_discover()
        return {}

    async def _fallback_yfinance_discover(self) -> dict[str, dict]:
        """Fall back to yfinance for price data."""
        logger.warning("Using yfinance as fallback data source for Markets.com instruments")
        self._use_yfinance = True

        try:
            import yfinance  # noqa: F811
            self._yf = yfinance
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return {}

        for symbol, yf_ticker in DEFAULT_INSTRUMENTS.items():
            self.symbols[symbol] = {
                "exchange": "markets.com",
                "yf_ticker": yf_ticker,
                "last_price": 0,
                "source": "yfinance",
            }

        logger.info("yfinance fallback: %d instruments configured", len(self.symbols))
        return self.symbols

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m",
                          limit: int = 200) -> pd.DataFrame:
        """Fetch historical OHLCV data."""
        if self._use_yfinance:
            return await self._fetch_yfinance(symbol, timeframe, limit)
        return await self._fetch_markets_com(symbol, timeframe, limit)

    async def _fetch_markets_com(self, symbol: str, timeframe: str,
                                 limit: int) -> pd.DataFrame:
        """Fetch from Markets.com REST API."""
        try:
            instrument_id = self.symbols.get(symbol, {}).get("instrument_id", symbol)
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                params = {
                    "instrument": instrument_id,
                    "timeframe": timeframe,
                    "limit": limit,
                }
                async with session.get(
                    f"{self.MARKETS_COM_BASE}/candles",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Markets.com candles for %s returned %d, using yfinance fallback",
                            symbol, resp.status,
                        )
                        return await self._fetch_yfinance(symbol, timeframe, limit)

                    data = await resp.json()
                    candles = data.get("candles", data.get("data", []))
                    rows = []
                    for c in candles:
                        rows.append({
                            "timestamp": pd.Timestamp(c.get("time", c.get("t", 0)), unit="s", tz="UTC"),
                            "open": float(c.get("open", c.get("o", 0))),
                            "high": float(c.get("high", c.get("h", 0))),
                            "low": float(c.get("low", c.get("l", 0))),
                            "close": float(c.get("close", c.get("c", 0))),
                            "volume": float(c.get("volume", c.get("v", 0))),
                        })
                    df = pd.DataFrame(rows)
                    if not df.empty:
                        df.set_index("timestamp", inplace=True)
                    self.candle_buffers[symbol] = df
                    return df
        except Exception as e:
            logger.error("Markets.com fetch error for %s: %s", symbol, e)
            return await self._fetch_yfinance(symbol, timeframe, limit)

    async def _fetch_yfinance(self, symbol: str, timeframe: str,
                              limit: int) -> pd.DataFrame:
        """Fetch from yfinance as fallback."""
        if self._yf is None:
            try:
                import yfinance
                self._yf = yfinance
            except ImportError:
                logger.error("yfinance not installed")
                return pd.DataFrame()

        yf_ticker = self.symbols.get(symbol, {}).get("yf_ticker")
        if not yf_ticker:
            yf_ticker = DEFAULT_INSTRUMENTS.get(symbol, symbol)

        try:
            # Map timeframe for yfinance
            interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}
            interval = interval_map.get(timeframe, "5m")
            period_map = {"1m": "1d", "5m": "5d", "15m": "5d", "1h": "1mo", "1d": "3mo"}
            period = period_map.get(interval, "5d")

            ticker = self._yf.Ticker(yf_ticker)
            df = await asyncio.to_thread(
                ticker.history, period=period, interval=interval
            )
            if df.empty:
                return df

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df = df[["open", "high", "low", "close", "volume"]].tail(limit)
            df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
            df.index.name = "timestamp"
            self.candle_buffers[symbol] = df
            return df
        except Exception as e:
            logger.error("yfinance fetch error for %s (%s): %s", symbol, yf_ticker, e)
            return pd.DataFrame()

    def set_candle_callback(self, callback: Callable):
        """Set callback for candle updates: callback(symbol, candle_df)."""
        self._candle_callback = callback

    async def start_polling(self):
        """Start periodic polling for all instruments."""
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Markets.com polling started (interval: %.1fh)", self.poll_interval / 3600)

    async def _poll_loop(self):
        """Main polling loop."""
        timeframe = self.config.get("timeframe", "5m")
        while self._running:
            for symbol in list(self.symbols.keys()):
                if not self._running:
                    break
                try:
                    df = await self.fetch_ohlcv(symbol, timeframe)
                    if not df.empty and self._candle_callback:
                        await self._candle_callback(symbol, df)
                except Exception as e:
                    logger.error("Poll error for %s: %s", symbol, e)
            await asyncio.sleep(self.poll_interval)

    async def stop(self):
        """Stop polling."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        logger.info("Markets.com feeds stopped")
