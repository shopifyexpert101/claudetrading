"""Composite confidence score calculator."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from signals.technical import get_higher_timeframe_trend

logger = logging.getLogger("trading_bot")


@dataclass
class ConfidenceScore:
    total: float
    signal_strength: float
    volume_confirmation: float
    trend_alignment: float
    sentiment_alignment: float


def compute_confidence(
    signal_direction: str,
    signal_type: str,
    indicator_value: float,
    threshold: float,
    volume: float,
    volume_avg_20: float,
    htf_df: pd.DataFrame | None,
    sentiment_score: float | None,
    weights: dict | None = None,
) -> ConfidenceScore:
    """Compute composite confidence score (0-100).

    Args:
        signal_direction: "LONG" or "SHORT"
        signal_type: e.g. "rsi", "macd", "spike"
        indicator_value: Current indicator reading
        threshold: Trigger threshold
        volume: Current candle volume
        volume_avg_20: 20-period rolling average volume
        htf_df: Higher-timeframe OHLCV DataFrame (or None)
        sentiment_score: Latest sentiment score for this asset (-1 to 1, or None)
        weights: Dict with keys signal_strength, volume_confirmation, trend_alignment, sentiment_alignment
    """
    if weights is None:
        weights = {
            "signal_strength": 0.30,
            "volume_confirmation": 0.20,
            "trend_alignment": 0.25,
            "sentiment_alignment": 0.25,
        }

    # 1. Signal Strength (0-100)
    sig_score = _calc_signal_strength(signal_type, indicator_value, threshold)

    # 2. Volume Confirmation (0-100)
    vol_score = _calc_volume_score(volume, volume_avg_20)

    # 3. Trend Alignment (0-100)
    trend_score = _calc_trend_alignment(signal_direction, htf_df)

    # 4. Sentiment Alignment (0-100)
    sent_score = _calc_sentiment_alignment(signal_direction, sentiment_score)

    total = (
        sig_score * weights["signal_strength"]
        + vol_score * weights["volume_confirmation"]
        + trend_score * weights["trend_alignment"]
        + sent_score * weights["sentiment_alignment"]
    )

    return ConfidenceScore(
        total=round(total, 1),
        signal_strength=round(sig_score, 1),
        volume_confirmation=round(vol_score, 1),
        trend_alignment=round(trend_score, 1),
        sentiment_alignment=round(sent_score, 1),
    )


def _calc_signal_strength(signal_type: str, value: float, threshold: float) -> float:
    """How far past the threshold the trigger is, normalized to 0-100."""
    if threshold == 0:
        return 50.0

    if signal_type == "rsi":
        # RSI at 22 when threshold is 30 → strong; RSI at 29 → weak
        distance = abs(value - threshold)
        max_distance = 30  # max expected distance
        return min(100, (distance / max_distance) * 100)

    elif signal_type == "spike":
        # How much the spike exceeds the threshold percentage
        overshoot = abs(value) - abs(threshold)
        return min(100, max(0, (overshoot / abs(threshold)) * 100 + 50))

    elif signal_type in ("macd", "ema_crossover"):
        # Crossover magnitude relative to price
        if threshold != 0:
            ratio = abs(value - threshold) / abs(threshold) * 100
            return min(100, ratio * 10 + 50)
        return 60.0

    elif signal_type == "bollinger":
        # How far the bounce is from the band
        if threshold != 0:
            ratio = abs(value - threshold) / abs(threshold) * 100
            return min(100, ratio * 50 + 50)
        return 60.0

    elif signal_type == "sr_breakout":
        # Breakout strength
        if threshold != 0:
            pct = abs(value - threshold) / abs(threshold) * 100
            return min(100, pct * 20 + 50)
        return 60.0

    # Default
    return 50.0


def _calc_volume_score(volume: float, volume_avg: float) -> float:
    """Volume spike ratio vs rolling average, normalized to 0-100.
    2x average = 50 points, 4x average = 100 points.
    """
    if volume_avg <= 0:
        return 50.0

    ratio = volume / volume_avg
    # Linear scale: 1x = 0, 2x = 50, 4x = 100
    score = (ratio - 1) * (100 / 3)
    return max(0, min(100, score))


def _calc_trend_alignment(direction: str, htf_df: pd.DataFrame | None) -> float:
    """Check signal direction vs higher timeframe trend.
    Aligned = 100, neutral = 50, against = 0.
    """
    trend = get_higher_timeframe_trend(htf_df)

    if trend == "neutral":
        return 50.0

    if direction == "LONG" and trend == "bullish":
        return 100.0
    elif direction == "SHORT" and trend == "bearish":
        return 100.0
    elif direction == "LONG" and trend == "bearish":
        return 0.0
    elif direction == "SHORT" and trend == "bullish":
        return 0.0

    return 50.0


def _calc_sentiment_alignment(direction: str, sentiment_score: float | None) -> float:
    """Sentiment alignment score.
    No news = 50 (neutral).
    Aligned = scale 50-100 based on magnitude.
    Opposed = scale 0-50.
    """
    if sentiment_score is None:
        return 50.0

    magnitude = abs(sentiment_score)  # 0 to 1

    if direction == "LONG" and sentiment_score > 0:
        return 50 + magnitude * 50
    elif direction == "SHORT" and sentiment_score < 0:
        return 50 + magnitude * 50
    elif direction == "LONG" and sentiment_score < 0:
        return 50 - magnitude * 50
    elif direction == "SHORT" and sentiment_score > 0:
        return 50 - magnitude * 50

    return 50.0
