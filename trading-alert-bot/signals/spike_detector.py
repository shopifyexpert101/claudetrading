"""Price spike detection module."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger("trading_bot")


@dataclass
class SpikeSignal:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    spike_pct: float
    volume_ratio: float
    price: float
    signal_type: str = "spike"
    description: str = ""


def detect_spike(
    symbol: str,
    df: pd.DataFrame,
    spike_pct: float = 2.0,
    volume_multiplier: float = 2.0,
) -> Optional[SpikeSignal]:
    """Detect price spike on the latest closed candle.

    Args:
        symbol: Trading pair symbol
        df: OHLCV DataFrame with at least 21 rows
        spike_pct: Minimum % move to qualify as spike
        volume_multiplier: Minimum volume ratio vs 20-period average

    Returns:
        SpikeSignal if detected, None otherwise
    """
    if df is None or len(df) < 21:
        return None

    latest = df.iloc[-1]
    candle_open = latest["open"]
    candle_close = latest["close"]
    candle_high = latest["high"]
    candle_low = latest["low"]
    volume = latest["volume"]

    if candle_open == 0:
        return None

    # Price move within the candle
    move_pct = abs((candle_close - candle_open) / candle_open) * 100

    if move_pct < spike_pct:
        return None

    # Volume confirmation: must exceed multiplier × 20-period rolling average
    vol_avg = df["volume"].iloc[-21:-1].mean()
    if vol_avg == 0:
        return None

    vol_ratio = volume / vol_avg
    if vol_ratio < volume_multiplier:
        return None

    # Determine direction
    if candle_close > candle_open:
        direction = "LONG"
        desc = f"Bullish spike: +{move_pct:.2f}% with {vol_ratio:.1f}x volume"
    else:
        direction = "SHORT"
        desc = f"Bearish spike: -{move_pct:.2f}% with {vol_ratio:.1f}x volume"

    logger.debug("Spike detected on %s: %s", symbol, desc)

    return SpikeSignal(
        symbol=symbol,
        direction=direction,
        spike_pct=move_pct,
        volume_ratio=vol_ratio,
        price=candle_close,
        description=desc,
    )
