"""ATR-based Stop Loss and Take Profit calculator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pandas_ta as ta

from utils.helpers import format_price

logger = logging.getLogger("trading_bot")


@dataclass
class SLTPLevels:
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    risk_reward: float
    atr_value: float
    sl_method: str  # "atr" or "swing"


def calculate_sl_tp(
    direction: str,
    entry_price: float,
    df: pd.DataFrame,
    asset_class: str,
    symbol: str = "",
    atr_period: int = 14,
    atr_multiplier_sl: float = 1.5,
    rr_tp1: float = 1.5,
    rr_tp2: float = 2.5,
    rr_tp3: float = 4.0,
    sr_lookback: int = 50,
) -> Optional[SLTPLevels]:
    """Calculate SL and TP levels for a trade alert.

    Args:
        direction: "LONG" or "SHORT"
        entry_price: Current market price
        df: OHLCV DataFrame
        asset_class: crypto, forex, commodity, index, stock
        symbol: Trading pair symbol
        atr_period: ATR calculation period
        atr_multiplier_sl: ATR multiplier for stop loss
        rr_tp1/tp2/tp3: Risk-reward ratios for take profit levels
        sr_lookback: Lookback for swing high/low fallback
    """
    if df is None or len(df) < atr_period + 1 or entry_price <= 0:
        return None

    # Calculate ATR
    atr_series = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
    atr_value = 0.0
    sl_method = "atr"

    if atr_series is not None and not atr_series.empty:
        atr_value = atr_series.iloc[-1]

    # Fallback to swing high/low if ATR unavailable
    if atr_value <= 0 or pd.isna(atr_value):
        sl_method = "swing"
        sl_price = _swing_sl(direction, df, sr_lookback)
        if sl_price is None:
            return None
    else:
        if direction == "LONG":
            sl_price = entry_price - (atr_value * atr_multiplier_sl)
        else:
            sl_price = entry_price + (atr_value * atr_multiplier_sl)

    # Ensure SL makes sense
    if direction == "LONG" and sl_price >= entry_price:
        sl_price = entry_price * 0.98  # 2% fallback
    elif direction == "SHORT" and sl_price <= entry_price:
        sl_price = entry_price * 1.02

    # Risk = distance from entry to SL
    risk = abs(entry_price - sl_price)

    # Take Profit levels
    if direction == "LONG":
        tp1 = entry_price + (risk * rr_tp1)
        tp2 = entry_price + (risk * rr_tp2)
        tp3_calc = entry_price + (risk * rr_tp3)
    else:
        tp1 = entry_price - (risk * rr_tp1)
        tp2 = entry_price - (risk * rr_tp2)
        tp3_calc = entry_price - (risk * rr_tp3)

    # TP3: use nearest key S/R level if closer to entry
    tp3 = _nearest_sr_tp3(direction, entry_price, tp3_calc, df, sr_lookback)

    # Risk/Reward ratio (using TP2)
    rr_ratio = abs(tp2 - entry_price) / risk if risk > 0 else 0

    return SLTPLevels(
        entry=entry_price,
        stop_loss=sl_price,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        risk_reward=round(rr_ratio, 2),
        atr_value=atr_value,
        sl_method=sl_method,
    )


def _swing_sl(direction: str, df: pd.DataFrame, lookback: int) -> Optional[float]:
    """Fallback SL using nearest swing low (LONG) or swing high (SHORT)."""
    lookback = min(lookback, len(df))
    window = df.iloc[-lookback:]

    if direction == "LONG":
        # Find swing lows
        lows = window["low"].values
        swing_lows = []
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
               lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append(lows[i])
        if swing_lows:
            return min(swing_lows[-3:])  # Use recent lowest swing low
        return window["low"].min()
    else:
        # Find swing highs
        highs = window["high"].values
        swing_highs = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
               highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append(highs[i])
        if swing_highs:
            return max(swing_highs[-3:])
        return window["high"].max()


def _nearest_sr_tp3(
    direction: str, entry: float, tp3_default: float,
    df: pd.DataFrame, lookback: int,
) -> float:
    """Use nearest key S/R level for TP3 if closer than default."""
    lookback = min(lookback, len(df))
    window = df.iloc[-lookback:]

    highs = window["high"].values
    lows = window["low"].values

    levels = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
           highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            levels.append(highs[i])
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
           lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            levels.append(lows[i])

    if not levels:
        return tp3_default

    if direction == "LONG":
        # Find S/R levels above entry
        candidates = [l for l in levels if l > entry]
        if candidates:
            nearest = min(candidates, key=lambda x: abs(x - entry))
            if abs(nearest - entry) < abs(tp3_default - entry):
                return nearest
    else:
        # Find S/R levels below entry
        candidates = [l for l in levels if l < entry]
        if candidates:
            nearest = max(candidates, key=lambda x: abs(entry - x))
            if abs(entry - nearest) < abs(entry - tp3_default):
                return nearest

    return tp3_default
