#!/usr/bin/env python3
"""Trading Alert Bot — Main entry point.

Monitors all available instruments on Binance and Markets.com,
runs signal detection, and sends alerts via Telegram / WhatsApp.

ALERT-ONLY — no order execution whatsoever.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from alerts.confidence import compute_confidence
from alerts.deduper import AlertDeduper
from alerts.formatter import format_telegram, format_whatsapp
from alerts.sl_tp import calculate_sl_tp
from data.market_feed import UnifiedMarketFeed
from notifiers.telegram_bot import TelegramNotifier
from notifiers.whatsapp_bot import WhatsAppNotifier
from signals.sentiment import SentimentAnalyzer
from signals.spike_detector import detect_spike
from signals.technical import check_all_signals, get_higher_timeframe_trend
from utils.helpers import classify_asset

logger = logging.getLogger("trading_bot")

# Dashboard integration (lazy import to avoid circular deps)
_dashboard = None

def _init_dashboard():
    global _dashboard
    from dashboard import state as dash_state, record_alert, record_signal, start_dashboard
    _dashboard = {
        "state": dash_state,
        "record_alert": record_alert,
        "record_signal": record_signal,
        "start": start_dashboard,
    }


class TradingAlertBot:
    """Main application orchestrator."""

    def __init__(self, config: dict, env: dict, dry_run: bool = False,
                 verbose: bool = False, single_asset: str = ""):
        self.config = config
        self.env = env
        self.dry_run = dry_run
        self.single_asset = single_asset

        if verbose:
            logging.getLogger("trading_bot").setLevel(logging.DEBUG)

        # Core components
        self.feed = UnifiedMarketFeed(config, env)
        self.sentiment = SentimentAnalyzer(config.get("signals", {}), env)

        # Rate limiter
        rl_cfg = config.get("rate_limiting", {})
        self.deduper = AlertDeduper(
            dedupe_window_min=rl_cfg.get("dedupe_window_min", 30),
            max_alerts_per_hour=rl_cfg.get("max_alerts_per_hour", 60),
            max_alerts_per_asset_per_hour=rl_cfg.get("max_alerts_per_asset_per_hour", 5),
        )

        # Notifiers
        self.telegram: TelegramNotifier | None = None
        self.whatsapp: WhatsAppNotifier | None = None

        notif_cfg = config.get("notifications", {})
        if notif_cfg.get("telegram", {}).get("enabled", False):
            self.telegram = TelegramNotifier(
                bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
                chat_id=env.get("TELEGRAM_CHAT_ID", ""),
            )
        if notif_cfg.get("whatsapp", {}).get("enabled", False):
            self.whatsapp = WhatsAppNotifier(
                account_sid=env.get("TWILIO_ACCOUNT_SID", ""),
                auth_token=env.get("TWILIO_AUTH_TOKEN", ""),
                from_number=env.get("TWILIO_WHATSAPP_FROM", ""),
                to_number=env.get("TWILIO_WHATSAPP_TO", ""),
            )

        # Latest sentiment cache: symbol -> score
        self._sentiment_cache: dict[str, float] = {}

    async def start(self):
        """Initialize and start the bot."""
        logger.info("=" * 60)
        logger.info("Trading Alert Bot starting%s", " (DRY RUN)" if self.dry_run else "")
        logger.info("=" * 60)

        # Update dashboard state
        if _dashboard:
            from datetime import datetime, timezone as tz
            _dashboard["state"].bot_running = True
            _dashboard["state"].dry_run = self.dry_run
            _dashboard["state"].start_time = datetime.now(tz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            _dashboard["state"].config = self.config

        # Initialize notifiers
        if self.telegram and not self.dry_run:
            await self.telegram.initialize()
        if self.whatsapp and not self.dry_run:
            await self.whatsapp.initialize()

        # Discover all symbols
        await self.feed.discover_all(single_asset=self.single_asset)

        if not self.feed.all_symbols:
            logger.error("No symbols discovered. Check exchange configuration.")
            return

        # Push symbol list to dashboard
        if _dashboard:
            _dashboard["state"].symbols_count = len(self.feed.all_symbols)
            _dashboard["state"].symbols = [
                {"symbol": s, "exchange": info.get("exchange", ""), "asset_class": info.get("asset_class", "")}
                for s, info in list(self.feed.all_symbols.items())[:500]
            ]

        # Set candle callback
        self.feed.set_candle_callback(self._on_candle)

        # Schedule sentiment polling
        sentiment_interval = self.config.get("signals", {}).get(
            "sentiment", {}
        ).get("news_poll_interval_min", 15)
        asyncio.create_task(self._sentiment_loop(sentiment_interval * 60))

        # Start data feeds
        logger.info("Starting data feeds...")
        await self.feed.start()

    async def _on_candle(self, symbol: str, df):
        """Called on every new candle close. Runs all signal checks."""
        try:
            await self._process_symbol(symbol, df)
        except Exception as e:
            logger.error("Error processing %s: %s", symbol, e, exc_info=True)

    async def _process_symbol(self, symbol: str, df):
        """Run signal detection pipeline for a single symbol."""
        import pandas as pd

        if df is None or df.empty or len(df) < 50:
            return

        info = self.feed.all_symbols.get(symbol, {})
        asset_class = info.get("asset_class", classify_asset(symbol, info.get("exchange", "")))
        exchange = info.get("exchange", "unknown")

        # Get asset-class-specific config overrides
        overrides = self.config.get("asset_class_overrides", {}).get(asset_class, {})
        signals_cfg = self.config.get("signals", {})

        # Merge overrides into signal config
        spike_cfg = {**signals_cfg.get("spike", {})}
        spike_cfg["spike_pct"] = overrides.get("spike_pct", spike_cfg.get("spike_pct", 2.0))
        spike_cfg["volume_multiplier"] = overrides.get(
            "volume_multiplier", spike_cfg.get("volume_multiplier", 2.0)
        )

        tech_cfg = dict(signals_cfg)
        rsi_cfg = {**tech_cfg.get("rsi", {})}
        rsi_cfg["rsi_oversold"] = overrides.get("rsi_oversold", rsi_cfg.get("rsi_oversold", 30))
        rsi_cfg["rsi_overbought"] = overrides.get("rsi_overbought", rsi_cfg.get("rsi_overbought", 70))
        tech_cfg["rsi"] = rsi_cfg

        min_confidence = overrides.get(
            "min_confidence",
            self.config.get("confidence", {}).get("min_confidence", 60),
        )

        # A. Spike detection
        spike = detect_spike(
            symbol, df,
            spike_pct=spike_cfg["spike_pct"],
            volume_multiplier=spike_cfg["volume_multiplier"],
        )
        if spike:
            await self._evaluate_and_alert(
                symbol, spike.direction, "spike",
                spike.price, spike.spike_pct, spike.spike_pct,
                df, asset_class, exchange, spike.description,
                min_confidence,
            )

        # B. Technical signals
        tech_signals = check_all_signals(symbol, df, tech_cfg)
        for sig in tech_signals:
            await self._evaluate_and_alert(
                symbol, sig.direction, sig.signal_type,
                sig.price, sig.indicator_value, sig.threshold,
                df, asset_class, exchange, sig.description,
                min_confidence,
            )

    async def _evaluate_and_alert(
        self,
        symbol: str,
        direction: str,
        signal_type: str,
        price: float,
        indicator_value: float,
        threshold: float,
        df,
        asset_class: str,
        exchange: str,
        description: str,
        min_confidence: float,
    ):
        """Compute confidence, check dedup, calculate SL/TP, send alert."""
        # Deduplication check
        can_send, reason = self.deduper.can_send(symbol, signal_type)
        if not can_send:
            return

        # Volume data
        volume = df["volume"].iloc[-1] if not df.empty else 0
        vol_avg = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else 0

        # Higher timeframe trend (use current data as approximation)
        htf_df = df  # In production, would fetch separate HTF data

        # Sentiment
        sentiment_score = self._sentiment_cache.get(symbol)

        # Compute confidence
        weights = self.config.get("confidence", {}).get("confidence_weights")
        confidence = compute_confidence(
            signal_direction=direction,
            signal_type=signal_type,
            indicator_value=indicator_value,
            threshold=threshold,
            volume=volume,
            volume_avg_20=vol_avg,
            htf_df=htf_df,
            sentiment_score=sentiment_score,
            weights=weights,
        )

        # Record signal detection for dashboard
        if _dashboard:
            _dashboard["record_signal"]()

        if confidence.total < min_confidence:
            logger.debug(
                "Signal %s on %s below confidence threshold (%.1f < %.1f)",
                signal_type, symbol, confidence.total, min_confidence,
            )
            return

        # Calculate SL/TP
        sl_tp_cfg = self.config.get("sl_tp", {})
        levels = calculate_sl_tp(
            direction=direction,
            entry_price=price,
            df=df,
            asset_class=asset_class,
            symbol=symbol,
            atr_period=sl_tp_cfg.get("atr_period", 14),
            atr_multiplier_sl=sl_tp_cfg.get("atr_multiplier_sl", 1.5),
            rr_tp1=sl_tp_cfg.get("rr_tp1", 1.5),
            rr_tp2=sl_tp_cfg.get("rr_tp2", 2.5),
            rr_tp3=sl_tp_cfg.get("rr_tp3", 4.0),
        )

        if levels is None:
            logger.warning("Could not calculate SL/TP for %s, skipping alert", symbol)
            return

        # Sentiment label
        if sentiment_score is not None:
            if sentiment_score > 0.2:
                sentiment_label = "Bullish"
            elif sentiment_score < -0.2:
                sentiment_label = "Bearish"
            else:
                sentiment_label = "Neutral"
        else:
            sentiment_label = "Neutral"
            sentiment_score = 0.0

        alert_id = f"{symbol}_{signal_type}_{uuid.uuid4().hex[:8]}"

        # Format messages
        tg_msg = format_telegram(
            symbol=symbol, direction=direction, exchange=exchange,
            asset_class=asset_class, trigger=description,
            sentiment_label=sentiment_label, sentiment_score=sentiment_score,
            levels=levels, confidence=confidence,
        )
        wa_msg = format_whatsapp(
            symbol=symbol, direction=direction, exchange=exchange,
            asset_class=asset_class, trigger=description,
            sentiment_label=sentiment_label, sentiment_score=sentiment_score,
            levels=levels, confidence=confidence,
        )

        # Send or log
        if self.dry_run:
            logger.info("=" * 50)
            logger.info("DRY RUN ALERT:\n%s", wa_msg)
            logger.info("=" * 50)
        else:
            tasks = []
            if self.telegram:
                tasks.append(self.telegram.send_alert(tg_msg, alert_id))
            if self.whatsapp:
                tasks.append(self.whatsapp.send_alert(wa_msg, alert_id))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # Record for dedup
        self.deduper.record_send(symbol, signal_type)

        # Push to dashboard
        if _dashboard:
            _dashboard["record_alert"]({
                "symbol": symbol,
                "direction": direction,
                "signal_type": signal_type,
                "exchange": exchange,
                "asset_class": asset_class,
                "description": description,
                "confidence": round(confidence.total, 1),
                "entry": price,
                "stop_loss": levels.stop_loss,
                "tp1": levels.tp1,
                "tp2": levels.tp2,
                "tp3": levels.tp3,
                "sentiment": sentiment_label,
            })

        logger.info(
            "Alert sent: %s %s %s (confidence: %.1f%%)",
            symbol, direction, signal_type, confidence.total,
        )

    async def _sentiment_loop(self, interval_sec: float):
        """Periodically poll news and update sentiment cache."""
        while True:
            try:
                signals = await self.sentiment.analyze()
                for sig in signals:
                    self._sentiment_cache[sig.symbol] = sig.score

                    # Sentiment signals can also trigger alerts directly
                    info = self.feed.all_symbols.get(sig.symbol, {})
                    if info:
                        df = self.feed.get_candle_buffer(sig.symbol)
                        if df is not None and not df.empty:
                            asset_class = info.get("asset_class", "crypto")
                            exchange = info.get("exchange", "unknown")
                            min_confidence = self.config.get(
                                "asset_class_overrides", {}
                            ).get(asset_class, {}).get(
                                "min_confidence",
                                self.config.get("confidence", {}).get("min_confidence", 60),
                            )
                            await self._evaluate_and_alert(
                                sig.symbol, sig.direction, "sentiment",
                                df["close"].iloc[-1], abs(sig.score), 0.5,
                                df, asset_class, exchange, sig.description,
                                min_confidence,
                            )

                # Push sentiment to dashboard
                if _dashboard:
                    _dashboard["state"].sentiment_cache = dict(self._sentiment_cache)

                logger.info(
                    "Sentiment update: %d signals from %d cached scores",
                    len(signals), len(self._sentiment_cache),
                )
            except Exception as e:
                logger.error("Sentiment loop error: %s", e, exc_info=True)

            await asyncio.sleep(interval_sec)

    async def stop(self):
        """Graceful shutdown."""
        if _dashboard:
            _dashboard["state"].bot_running = False
        logger.info("Shutting down Trading Alert Bot...")
        await self.feed.stop()
        if self.telegram:
            await self.telegram.shutdown()
        if self.whatsapp:
            await self.whatsapp.shutdown()
        logger.info("Bot stopped.")


def load_config(config_path: str = "config.yaml") -> dict:
    """Load YAML configuration."""
    path = Path(config_path)
    if not path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_env() -> dict:
    """Load environment variables from .env file."""
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    else:
        logger.warning(".env file not found. Copy .env.example to .env and configure.")

    return {
        "BINANCE_API_KEY": os.getenv("BINANCE_API_KEY", ""),
        "BINANCE_API_SECRET": os.getenv("BINANCE_API_SECRET", ""),
        "MARKETS_COM_API_KEY": os.getenv("MARKETS_COM_API_KEY", ""),
        "MARKETS_COM_API_SECRET": os.getenv("MARKETS_COM_API_SECRET", ""),
        "MARKETS_COM_ACCOUNT_ID": os.getenv("MARKETS_COM_ACCOUNT_ID", ""),
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_WHATSAPP_FROM": os.getenv("TWILIO_WHATSAPP_FROM", ""),
        "TWILIO_WHATSAPP_TO": os.getenv("TWILIO_WHATSAPP_TO", ""),
        "NEWSAPI_KEY": os.getenv("NEWSAPI_KEY", ""),
        "FINNHUB_API_KEY": os.getenv("FINNHUB_API_KEY", ""),
        "ALPHA_VANTAGE_KEY": os.getenv("ALPHA_VANTAGE_KEY", ""),
        "CRYPTOPANIC_API_KEY": os.getenv("CRYPTOPANIC_API_KEY", ""),
    }


async def main():
    parser = argparse.ArgumentParser(description="Trading Alert Bot")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log alerts to console only, no messages sent",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--asset", type=str, default="",
        help="Monitor only this symbol (e.g. BTCUSDT) for testing",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Launch live web dashboard on port 5050",
    )
    parser.add_argument(
        "--dashboard-port", type=int, default=5050,
        help="Dashboard port (default: 5050)",
    )
    args = parser.parse_args()

    # Start dashboard if requested
    if args.dashboard:
        _init_dashboard()
        _dashboard["start"](port=args.dashboard_port)
        logger.info("Dashboard available at http://localhost:%d", args.dashboard_port)

    config = load_config(args.config)
    env = load_env()

    bot = TradingAlertBot(
        config=config,
        env=env,
        dry_run=args.dry_run,
        verbose=args.verbose,
        single_asset=args.asset,
    )

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))

    try:
        await bot.start()
        # Keep running
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
