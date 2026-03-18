"""Alert deduplication and rate limiting."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger("trading_bot")


class AlertDeduper:
    """Prevent duplicate and excessive alert messages."""

    def __init__(
        self,
        dedupe_window_min: int = 30,
        max_alerts_per_hour: int = 60,
        max_alerts_per_asset_per_hour: int = 5,
    ):
        self.dedupe_window = dedupe_window_min * 60  # seconds
        self.max_per_hour = max_alerts_per_hour
        self.max_per_asset_hour = max_alerts_per_asset_per_hour

        # (asset, signal_type) -> last send timestamp
        self._dedupe_map: dict[tuple[str, str], float] = {}

        # Global alert timestamps (last hour)
        self._global_timestamps: list[float] = []

        # Per-asset alert timestamps
        self._asset_timestamps: dict[str, list[float]] = defaultdict(list)

    def can_send(self, symbol: str, signal_type: str) -> tuple[bool, str]:
        """Check if an alert can be sent. Returns (allowed, reason)."""
        now = time.time()
        self._cleanup(now)

        # 1. Deduplication check
        key = (symbol, signal_type)
        if key in self._dedupe_map:
            elapsed = now - self._dedupe_map[key]
            if elapsed < self.dedupe_window:
                remaining = int((self.dedupe_window - elapsed) / 60)
                reason = (
                    f"Duplicate suppressed: {symbol} {signal_type} "
                    f"(sent {int(elapsed/60)}m ago, cooldown {remaining}m remaining)"
                )
                logger.info(reason)
                return False, reason

        # 2. Global rate limit
        if len(self._global_timestamps) >= self.max_per_hour:
            reason = f"Global rate limit hit: {self.max_per_hour}/hour"
            logger.warning(reason)
            return False, reason

        # 3. Per-asset rate limit
        asset_ts = self._asset_timestamps[symbol]
        if len(asset_ts) >= self.max_per_asset_hour:
            reason = f"Per-asset rate limit hit for {symbol}: {self.max_per_asset_hour}/hour"
            logger.warning(reason)
            return False, reason

        return True, ""

    def record_send(self, symbol: str, signal_type: str):
        """Record that an alert was sent."""
        now = time.time()
        self._dedupe_map[(symbol, signal_type)] = now
        self._global_timestamps.append(now)
        self._asset_timestamps[symbol].append(now)

    def _cleanup(self, now: float):
        """Remove expired entries."""
        one_hour_ago = now - 3600

        # Cleanup global timestamps
        self._global_timestamps = [t for t in self._global_timestamps if t > one_hour_ago]

        # Cleanup per-asset timestamps
        for asset in list(self._asset_timestamps.keys()):
            self._asset_timestamps[asset] = [
                t for t in self._asset_timestamps[asset] if t > one_hour_ago
            ]
            if not self._asset_timestamps[asset]:
                del self._asset_timestamps[asset]

        # Cleanup dedupe map (remove entries older than window)
        expired_keys = [
            k for k, ts in self._dedupe_map.items()
            if now - ts > self.dedupe_window
        ]
        for k in expired_keys:
            del self._dedupe_map[k]
