"""
Multi-timeframe scanner for CLAWBOT v2.
Scans H1 + H4 for trade setups using ATR expansion and volume z-score filters.
Designed with loose filters for defensive/low-vol stocks.
"""
import numpy as np
import pandas as pd
from config import settings
from utils.mt5_helper import get_bars, get_symbol_info
from utils.logger import log


class Scanner:
    def __init__(self):
        self.timeframes = settings.SCANNER_TIMEFRAMES
        self.atr_period = settings.ATR_PERIOD
        self.atr_ratio = settings.ATR_EXPANSION_RATIO
        self.vol_zscore_min = settings.VOLUME_ZSCORE_MIN
        self.min_bars = settings.MIN_BARS_REQUIRED

    def scan_all(self) -> list:
        """Scan all symbols and return candidates that pass filters."""
        candidates = []
        for symbol in settings.SYMBOLS:
            result = self.scan_symbol(symbol)
            if result:
                candidates.append(result)
                log.info(f"PASS | {symbol} | ATR ratio: {result['atr_ratio']:.3f} | Vol Z: {result['volume_zscore']:.2f}")
            else:
                log.debug(f"SKIP | {symbol}")

        log.info(f"Scanner found {len(candidates)}/{len(settings.SYMBOLS)} candidates")
        return candidates

    def scan_symbol(self, symbol: str) -> dict:
        """Scan a single symbol across multiple timeframes."""
        tf_data = {}
        for tf in self.timeframes:
            bars = get_bars(symbol, tf, count=self.min_bars + self.atr_period + 50)
            if bars.empty or len(bars) < self.min_bars:
                log.debug(f"{symbol} {tf}: insufficient bars ({len(bars)})")
                return None
            tf_data[tf] = bars

        # Use H1 as primary timeframe for signals
        h1 = tf_data.get("H1")
        h4 = tf_data.get("H4")

        if h1 is None or h4 is None:
            return None

        # Calculate ATR on both timeframes
        h1_atr = self._calc_atr(h1)
        h4_atr = self._calc_atr(h4)

        if h1_atr is None or h4_atr is None:
            return None

        # ATR expansion filter: current ATR vs average ATR
        current_atr = h1_atr.iloc[-1]
        avg_atr = h1_atr.iloc[-self.atr_period:].mean()
        atr_ratio = current_atr / avg_atr if avg_atr > 0 else 0

        # Volume z-score on H1
        vol_zscore = self._calc_volume_zscore(h1)

        # Pass if ATR is expanding enough and volume isn't dead
        if atr_ratio < self.atr_ratio:
            return None
        if vol_zscore < self.vol_zscore_min:
            return None

        # Determine trend from H4
        h4_trend = self._detect_trend(h4)
        h1_trend = self._detect_trend(h1)

        # Get symbol info for spread/point data
        sym_info = get_symbol_info(symbol)

        return {
            "symbol": symbol,
            "h1_trend": h1_trend,
            "h4_trend": h4_trend,
            "atr_ratio": atr_ratio,
            "atr_value": current_atr,
            "volume_zscore": vol_zscore,
            "h1_close": float(h1["Close"].iloc[-1]),
            "h4_close": float(h4["Close"].iloc[-1]),
            "h1_data": h1.tail(50).to_dict(),
            "h4_data": h4.tail(20).to_dict(),
            "spread": sym_info.get("spread", 0),
            "point": sym_info.get("point", 0.01),
            "digits": sym_info.get("digits", 2),
        }

    def _calc_atr(self, df: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range."""
        if len(df) < self.atr_period + 1:
            return None

        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=self.atr_period).mean()

        return atr

    def _calc_volume_zscore(self, df: pd.DataFrame) -> float:
        """Calculate volume z-score (how current volume compares to recent average)."""
        if len(df) < 20:
            return 0.0

        volumes = df["Volume"].tail(50)
        current_vol = volumes.iloc[-1]
        mean_vol = volumes.mean()
        std_vol = volumes.std()

        if std_vol == 0:
            return 0.0

        return (current_vol - mean_vol) / std_vol

    def _detect_trend(self, df: pd.DataFrame) -> str:
        """Simple trend detection using moving averages."""
        if len(df) < 50:
            return "unknown"

        close = df["Close"]
        sma_20 = close.rolling(20).mean().iloc[-1]
        sma_50 = close.rolling(50).mean().iloc[-1]
        current = close.iloc[-1]

        if current > sma_20 > sma_50:
            return "bullish"
        elif current < sma_20 < sma_50:
            return "bearish"
        elif abs(current - sma_20) / sma_20 < 0.005:
            return "ranging"
        else:
            return "mixed"
