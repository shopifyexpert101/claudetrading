"""Technical signal engine using pandas-ta indicators."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger("trading_bot")


@dataclass
class TechnicalSignal:
    symbol: str
    direction: str  # "LONG" or "SHORT"
    signal_type: str  # "rsi", "macd", "bollinger", "ema_crossover", "sr_breakout"
    price: float
    description: str = ""
    indicator_value: float = 0.0
    threshold: float = 0.0
    volume_ratio: float = 0.0


def check_all_signals(
    symbol: str,
    df: pd.DataFrame,
    config: dict,
) -> list[TechnicalSignal]:
    """Run all technical checks on the latest candle. Returns list of triggered signals."""
    if df is None or len(df) < 50:
        return []

    signals: list[TechnicalSignal] = []

    try:
        sig = check_rsi(symbol, df, config.get("rsi", {}))
        if sig:
            signals.append(sig)
    except Exception as e:
        logger.error("RSI check failed for %s: %s", symbol, e)

    try:
        sig = check_macd(symbol, df, config.get("macd", {}))
        if sig:
            signals.append(sig)
    except Exception as e:
        logger.error("MACD check failed for %s: %s", symbol, e)

    try:
        sig = check_bollinger(symbol, df, config.get("bollinger", {}))
        if sig:
            signals.append(sig)
    except Exception as e:
        logger.error("Bollinger check failed for %s: %s", symbol, e)

    try:
        sig = check_ema_crossover(symbol, df, config.get("ema_crossover", {}))
        if sig:
            signals.append(sig)
    except Exception as e:
        logger.error("EMA crossover check failed for %s: %s", symbol, e)

    try:
        sig = check_sr_breakout(symbol, df, config.get("support_resistance", {}))
        if sig:
            signals.append(sig)
    except Exception as e:
        logger.error("S/R breakout check failed for %s: %s", symbol, e)

    return signals


def check_rsi(symbol: str, df: pd.DataFrame, cfg: dict) -> Optional[TechnicalSignal]:
    """RSI crossover signals."""
    period = cfg.get("period", 14)
    oversold = cfg.get("rsi_oversold", 30)
    overbought = cfg.get("rsi_overbought", 70)

    rsi = ta.rsi(df["close"], length=period)
    if rsi is None or len(rsi) < 2:
        return None

    current = rsi.iloc[-1]
    previous = rsi.iloc[-2]

    # LONG: RSI crosses UP through oversold level
    if previous < oversold <= current:
        return TechnicalSignal(
            symbol=symbol, direction="LONG", signal_type="rsi",
            price=df["close"].iloc[-1],
            indicator_value=current, threshold=oversold,
            description=f"RSI crossed up through {oversold} (now {current:.1f})",
        )

    # SHORT: RSI crosses DOWN through overbought level
    if previous > overbought >= current:
        return TechnicalSignal(
            symbol=symbol, direction="SHORT", signal_type="rsi",
            price=df["close"].iloc[-1],
            indicator_value=current, threshold=overbought,
            description=f"RSI crossed down through {overbought} (now {current:.1f})",
        )

    return None


def check_macd(symbol: str, df: pd.DataFrame, cfg: dict) -> Optional[TechnicalSignal]:
    """MACD line / signal line crossover."""
    fast = cfg.get("fast", 12)
    slow = cfg.get("slow", 26)
    signal = cfg.get("signal", 9)

    macd_df = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
    if macd_df is None or len(macd_df) < 2:
        return None

    macd_col = f"MACD_{fast}_{slow}_{signal}"
    signal_col = f"MACDs_{fast}_{slow}_{signal}"

    if macd_col not in macd_df.columns or signal_col not in macd_df.columns:
        return None

    curr_macd = macd_df[macd_col].iloc[-1]
    prev_macd = macd_df[macd_col].iloc[-2]
    curr_signal = macd_df[signal_col].iloc[-1]
    prev_signal = macd_df[signal_col].iloc[-2]

    # LONG: MACD crosses above signal
    if prev_macd <= prev_signal and curr_macd > curr_signal:
        return TechnicalSignal(
            symbol=symbol, direction="LONG", signal_type="macd",
            price=df["close"].iloc[-1],
            indicator_value=curr_macd,
            description=f"MACD bullish crossover ({curr_macd:.4f} > {curr_signal:.4f})",
        )

    # SHORT: MACD crosses below signal
    if prev_macd >= prev_signal and curr_macd < curr_signal:
        return TechnicalSignal(
            symbol=symbol, direction="SHORT", signal_type="macd",
            price=df["close"].iloc[-1],
            indicator_value=curr_macd,
            description=f"MACD bearish crossover ({curr_macd:.4f} < {curr_signal:.4f})",
        )

    return None


def check_bollinger(symbol: str, df: pd.DataFrame, cfg: dict) -> Optional[TechnicalSignal]:
    """Bollinger Band bounce signals."""
    period = cfg.get("period", 20)
    std_dev = cfg.get("std_dev", 2.0)

    bb = ta.bbands(df["close"], length=period, std=std_dev)
    if bb is None or len(bb) < 2:
        return None

    lower_col = f"BBL_{period}_{std_dev}"
    upper_col = f"BBU_{period}_{std_dev}"

    if lower_col not in bb.columns or upper_col not in bb.columns:
        return None

    curr_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]
    curr_lower = bb[lower_col].iloc[-1]
    prev_lower = bb[lower_col].iloc[-2]
    curr_upper = bb[upper_col].iloc[-1]
    prev_upper = bb[upper_col].iloc[-2]

    # LONG: price was below lower band, now bounced back inside
    if prev_close < prev_lower and curr_close >= curr_lower:
        return TechnicalSignal(
            symbol=symbol, direction="LONG", signal_type="bollinger",
            price=curr_close,
            indicator_value=curr_lower,
            description=f"Bollinger lower band bounce (price {curr_close:.4f} > BB lower {curr_lower:.4f})",
        )

    # SHORT: price was above upper band, now dropped back inside
    if prev_close > prev_upper and curr_close <= curr_upper:
        return TechnicalSignal(
            symbol=symbol, direction="SHORT", signal_type="bollinger",
            price=curr_close,
            indicator_value=curr_upper,
            description=f"Bollinger upper band rejection (price {curr_close:.4f} < BB upper {curr_upper:.4f})",
        )

    return None


def check_ema_crossover(symbol: str, df: pd.DataFrame, cfg: dict) -> Optional[TechnicalSignal]:
    """EMA fast/slow crossover."""
    fast_period = cfg.get("fast_period", 9)
    slow_period = cfg.get("slow_period", 21)

    ema_fast = ta.ema(df["close"], length=fast_period)
    ema_slow = ta.ema(df["close"], length=slow_period)

    if ema_fast is None or ema_slow is None or len(ema_fast) < 2:
        return None

    curr_fast = ema_fast.iloc[-1]
    prev_fast = ema_fast.iloc[-2]
    curr_slow = ema_slow.iloc[-1]
    prev_slow = ema_slow.iloc[-2]

    # LONG: fast EMA crosses above slow EMA
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return TechnicalSignal(
            symbol=symbol, direction="LONG", signal_type="ema_crossover",
            price=df["close"].iloc[-1],
            indicator_value=curr_fast,
            description=f"EMA{fast_period} crossed above EMA{slow_period} ({curr_fast:.4f} > {curr_slow:.4f})",
        )

    # SHORT: fast EMA crosses below slow EMA
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return TechnicalSignal(
            symbol=symbol, direction="SHORT", signal_type="ema_crossover",
            price=df["close"].iloc[-1],
            indicator_value=curr_fast,
            description=f"EMA{fast_period} crossed below EMA{slow_period} ({curr_fast:.4f} < {curr_slow:.4f})",
        )

    return None


def check_sr_breakout(symbol: str, df: pd.DataFrame, cfg: dict) -> Optional[TechnicalSignal]:
    """Support/Resistance breakout detection."""
    lookback = cfg.get("sr_lookback_periods", 100)
    lookback = min(lookback, len(df) - 1)

    if lookback < 20:
        return None

    window = df.iloc[-lookback - 1:-1]  # Exclude current candle for S/R calc
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    # Find swing highs and lows (local extrema over 5-bar windows)
    swing_highs = []
    swing_lows = []

    highs = window["high"].values
    lows = window["low"].values

    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
           highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
           lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            swing_lows.append(lows[i])

    if not swing_highs and not swing_lows:
        return None

    # Volume confirmation
    vol_avg = df["volume"].iloc[-21:-1].mean()
    vol_ratio = curr["volume"] / vol_avg if vol_avg > 0 else 0

    # Resistance breakout (LONG)
    if swing_highs:
        resistance = max(swing_highs[-5:]) if len(swing_highs) >= 5 else max(swing_highs)
        if prev["close"] <= resistance < curr["close"] and vol_ratio >= 1.5:
            return TechnicalSignal(
                symbol=symbol, direction="LONG", signal_type="sr_breakout",
                price=curr["close"],
                indicator_value=resistance,
                volume_ratio=vol_ratio,
                description=f"Resistance breakout at {resistance:.4f} with {vol_ratio:.1f}x volume",
            )

    # Support breakdown (SHORT)
    if swing_lows:
        support = min(swing_lows[-5:]) if len(swing_lows) >= 5 else min(swing_lows)
        if prev["close"] >= support > curr["close"] and vol_ratio >= 1.5:
            return TechnicalSignal(
                symbol=symbol, direction="SHORT", signal_type="sr_breakout",
                price=curr["close"],
                indicator_value=support,
                volume_ratio=vol_ratio,
                description=f"Support breakdown at {support:.4f} with {vol_ratio:.1f}x volume",
            )

    return None


def get_higher_timeframe_trend(df_htf: pd.DataFrame) -> str:
    """Determine trend from higher timeframe data. Returns 'bullish', 'bearish', or 'neutral'."""
    if df_htf is None or len(df_htf) < 21:
        return "neutral"

    ema_fast = ta.ema(df_htf["close"], length=9)
    ema_slow = ta.ema(df_htf["close"], length=21)

    if ema_fast is None or ema_slow is None:
        return "neutral"

    fast = ema_fast.iloc[-1]
    slow = ema_slow.iloc[-1]

    if fast > slow * 1.001:
        return "bullish"
    elif fast < slow * 0.999:
        return "bearish"
    return "neutral"
