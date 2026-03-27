"""
MT5 connection and utility functions.
Handles symbol resolution for Markets.com naming conventions.
"""
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from config import settings
from utils.logger import log


def connect_mt5() -> bool:
    """Initialize and connect to MT5."""
    if not mt5.initialize(path=settings.MT5_PATH or None):
        log.error(f"MT5 init failed: {mt5.last_error()}")
        return False

    authorized = mt5.login(
        login=settings.MT5_ACCOUNT,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
    )
    if not authorized:
        log.error(f"MT5 login failed: {mt5.last_error()}")
        return False

    info = mt5.account_info()
    log.info(f"MT5 connected | Account: {info.login} | Balance: ${info.balance:.2f}")
    return True


def resolve_symbol(symbol: str) -> str:
    """Resolve our symbol name to the broker's actual symbol name."""
    # First check direct mapping
    mapped = settings.SYMBOL_MAP.get(symbol, symbol)

    # Verify symbol exists on broker
    info = mt5.symbol_info(mapped)
    if info is not None:
        if not info.visible:
            mt5.symbol_select(mapped, True)
        return mapped

    # Try common broker naming patterns
    patterns = [
        mapped,
        f"{mapped}.r",
        f"{mapped}.i",
        f"#{mapped}",
        mapped.replace("/", ""),
    ]

    for pattern in patterns:
        info = mt5.symbol_info(pattern)
        if info is not None:
            if not info.visible:
                mt5.symbol_select(pattern, True)
            log.info(f"Symbol resolved: {symbol} -> {pattern}")
            settings.SYMBOL_MAP[symbol] = pattern
            return pattern

    log.warning(f"Symbol not found on broker: {symbol}")
    return None


def get_timeframe(tf_str: str):
    """Convert string timeframe to MT5 constant."""
    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
    }
    return tf_map.get(tf_str)


def get_bars(symbol: str, timeframe: str, count: int = 200) -> pd.DataFrame:
    """Fetch OHLCV bars from MT5."""
    broker_symbol = resolve_symbol(symbol)
    if not broker_symbol:
        return pd.DataFrame()

    tf = get_timeframe(timeframe)
    if tf is None:
        log.error(f"Invalid timeframe: {timeframe}")
        return pd.DataFrame()

    rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        log.warning(f"No bars for {symbol} {timeframe}")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "tick_volume": "Volume"
    }, inplace=True)

    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_account_info() -> dict:
    """Get current account info."""
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "profit": info.profit,
        "leverage": info.leverage,
    }


def get_open_positions() -> list:
    """Get all currently open positions."""
    positions = mt5.positions_get()
    if positions is None:
        return []
    return [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": p.volume,
            "open_price": p.price_open,
            "current_price": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "swap": p.swap,
            "time": datetime.fromtimestamp(p.time, tz=timezone.utc),
            "comment": p.comment,
        }
        for p in positions
    ]


def get_symbol_info(symbol: str) -> dict:
    """Get symbol trading info (point, digits, min lot, etc.)."""
    broker_symbol = resolve_symbol(symbol)
    if not broker_symbol:
        return {}

    info = mt5.symbol_info(broker_symbol)
    if info is None:
        return {}

    return {
        "name": info.name,
        "point": info.point,
        "digits": info.digits,
        "spread": info.spread,
        "min_lot": info.volume_min,
        "max_lot": info.volume_max,
        "lot_step": info.volume_step,
        "trade_mode": info.trade_mode,
        "filling_mode": info.filling_mode,
        "bid": info.bid,
        "ask": info.ask,
    }


def shutdown_mt5():
    """Clean shutdown of MT5."""
    mt5.shutdown()
    log.info("MT5 disconnected")
