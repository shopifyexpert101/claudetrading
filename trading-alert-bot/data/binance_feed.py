"""Binance data feed — REST discovery + WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import ccxt
import pandas as pd
import websockets

logger = logging.getLogger("trading_bot")


class BinanceFeed:
    """Manages Binance symbol discovery and live kline streaming."""

    WS_SPOT = "wss://stream.binance.com:9443/stream?streams="
    WS_FUTURES = "wss://fstream.binance.com/stream?streams="

    def __init__(self, config: dict, api_key: str = "", api_secret: str = ""):
        self.config = config
        self.exchange = ccxt.binance({
            "apiKey": api_key or None,
            "secret": api_secret or None,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        self.futures_exchange = ccxt.binance({
            "apiKey": api_key or None,
            "secret": api_secret or None,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        self.symbols: dict[str, dict] = {}  # symbol -> {market, type, ...}
        self._ws_tasks: list[asyncio.Task] = []
        self._running = False
        self._candle_callback: Optional[Callable] = None
        # In-memory candle buffers: symbol -> DataFrame
        self.candle_buffers: dict[str, pd.DataFrame] = {}

    async def discover_symbols(self) -> dict[str, dict]:
        """Auto-discover all tradeable symbols filtered by volume and quote currency."""
        quote_currencies = set(self.config.get("quote_currencies", ["USDT"]))
        min_volume = self.config.get("min_24h_volume_usd", 5_000_000)
        markets_cfg = self.config.get("markets", ["spot"])

        discovered: dict[str, dict] = {}

        for market_type in markets_cfg:
            try:
                ex = self.exchange if market_type == "spot" else self.futures_exchange
                await asyncio.to_thread(ex.load_markets)
                tickers = await asyncio.to_thread(ex.fetch_tickers)

                for symbol, ticker in tickers.items():
                    market_info = ex.markets.get(symbol, {})
                    quote = market_info.get("quote", "")
                    if quote not in quote_currencies:
                        continue

                    vol_usd = ticker.get("quoteVolume", 0) or 0
                    # For BTC-quoted pairs, estimate USD volume
                    if quote == "BTC" and "BTC/USDT" in tickers:
                        btc_price = tickers["BTC/USDT"].get("last", 0) or 0
                        vol_usd = vol_usd * btc_price
                    elif quote == "ETH" and "ETH/USDT" in tickers:
                        eth_price = tickers["ETH/USDT"].get("last", 0) or 0
                        vol_usd = vol_usd * eth_price
                    elif quote == "BNB" and "BNB/USDT" in tickers:
                        bnb_price = tickers["BNB/USDT"].get("last", 0) or 0
                        vol_usd = vol_usd * bnb_price

                    if vol_usd < min_volume:
                        continue

                    ws_symbol = symbol.replace("/", "").lower()
                    discovered[symbol] = {
                        "exchange": "binance",
                        "market_type": market_type,
                        "quote": quote,
                        "volume_usd": vol_usd,
                        "ws_symbol": ws_symbol,
                        "last_price": ticker.get("last", 0),
                    }

                logger.info(
                    "Binance %s: discovered %d symbols (filtered from %d)",
                    market_type, len([d for d in discovered.values() if d["market_type"] == market_type]),
                    len(tickers),
                )
            except Exception as e:
                logger.error("Binance %s discovery failed: %s", market_type, e)

        self.symbols = discovered
        return discovered

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", limit: int = 200) -> pd.DataFrame:
        """Fetch historical OHLCV for a symbol."""
        try:
            info = self.symbols.get(symbol, {})
            ex = self.futures_exchange if info.get("market_type") == "futures" else self.exchange
            data = await asyncio.to_thread(ex.fetch_ohlcv, symbol, timeframe, limit=limit)
            df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            self.candle_buffers[symbol] = df
            return df
        except Exception as e:
            logger.error("Failed to fetch OHLCV for %s: %s", symbol, e)
            return pd.DataFrame()

    def set_candle_callback(self, callback: Callable):
        """Set callback invoked on each candle close: callback(symbol, candle_df)."""
        self._candle_callback = callback

    async def start_websockets(self):
        """Start websocket streams for all discovered symbols."""
        self._running = True
        timeframe = self.config.get("timeframe", "5m")

        # Group symbols by market type
        spot_symbols = [s for s, info in self.symbols.items() if info["market_type"] == "spot"]
        futures_symbols = [s for s, info in self.symbols.items() if info["market_type"] == "futures"]

        # Binance combined streams max ~200 per connection
        batch_size = 150

        for i in range(0, len(spot_symbols), batch_size):
            batch = spot_symbols[i:i + batch_size]
            streams = [f"{self.symbols[s]['ws_symbol']}@kline_{timeframe}" for s in batch]
            task = asyncio.create_task(
                self._ws_listen(self.WS_SPOT + "/".join(streams), batch, "spot")
            )
            self._ws_tasks.append(task)

        for i in range(0, len(futures_symbols), batch_size):
            batch = futures_symbols[i:i + batch_size]
            streams = [f"{self.symbols[s]['ws_symbol']}@kline_{timeframe}" for s in batch]
            task = asyncio.create_task(
                self._ws_listen(self.WS_FUTURES + "/".join(streams), batch, "futures")
            )
            self._ws_tasks.append(task)

        logger.info(
            "Started %d WebSocket connections for %d symbols",
            len(self._ws_tasks), len(self.symbols),
        )

    async def _ws_listen(self, url: str, symbols: list[str], market_type: str):
        """Listen to a combined WebSocket stream with auto-reconnect."""
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1
                    logger.info("WebSocket connected: %s (%d symbols)", market_type, len(symbols))
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(msg)
                            await self._process_kline(data)
                        except json.JSONDecodeError:
                            continue
            except websockets.ConnectionClosed:
                logger.warning("WebSocket %s closed, reconnecting in %ds...", market_type, backoff)
            except Exception as e:
                logger.error("WebSocket %s error: %s, reconnecting in %ds...", market_type, e, backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _process_kline(self, data: dict):
        """Process a kline websocket message."""
        payload = data.get("data", data)
        kline = payload.get("k", {})
        if not kline:
            return

        is_closed = kline.get("x", False)
        ws_symbol = kline.get("s", "").upper()

        # Map ws_symbol back to ccxt symbol
        symbol = None
        for sym, info in self.symbols.items():
            if info["ws_symbol"] == ws_symbol.lower():
                symbol = sym
                break

        if not symbol:
            return

        candle = {
            "timestamp": pd.Timestamp(kline["t"], unit="ms", tz="UTC"),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
        }

        # Update buffer
        if symbol in self.candle_buffers and not self.candle_buffers[symbol].empty:
            df = self.candle_buffers[symbol]
            ts = candle["timestamp"]
            row = pd.DataFrame([candle]).set_index("timestamp")
            if ts in df.index:
                df.loc[ts] = row.iloc[0]
            else:
                self.candle_buffers[symbol] = pd.concat([df, row]).tail(500)
        else:
            self.candle_buffers[symbol] = pd.DataFrame([candle]).set_index("timestamp")

        # Fire callback on candle close
        if is_closed and self._candle_callback:
            try:
                await self._candle_callback(symbol, self.candle_buffers[symbol].copy())
            except Exception as e:
                logger.error("Candle callback error for %s: %s", symbol, e)

    async def stop(self):
        """Stop all websocket streams."""
        self._running = False
        for task in self._ws_tasks:
            task.cancel()
        self._ws_tasks.clear()
        logger.info("Binance feeds stopped")
