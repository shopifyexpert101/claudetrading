"""
CLAWBOT v2 - Main Orchestrator
AI-powered trading bot: Scanner -> Sentiment -> Brain -> Scorer -> Risk -> Executor -> Position Manager

Schedule: 4 scans/day at configured UTC hours
Dashboard: http://localhost:8050
"""
import sys
import time
import threading
from datetime import datetime, timezone

from config import settings
from utils.logger import log
from utils.mt5_helper import connect_mt5, shutdown_mt5, get_account_info
from scanner import Scanner
from sentiment import SentimentAnalyzer
from brain import TradeBrain
from scorer import TradeScorer
from risk import RiskManager
from executor import Executor
from position_manager import PositionManager
from dashboard import create_dashboard


class ClawBot:
    def __init__(self):
        self.scanner = Scanner()
        self.sentiment = SentimentAnalyzer()
        self.brain = TradeBrain()
        self.scorer = TradeScorer()
        self.risk = RiskManager()
        self.executor = Executor()
        self.position_mgr = PositionManager()
        self.scans_today = 0
        self.last_scan_hour = -1
        self.running = True

    def start(self):
        """Start the trading bot."""
        log.info("=" * 60)
        log.info("CLAWBOT v2 Starting")
        log.info("=" * 60)

        # Connect to MT5
        if not connect_mt5():
            log.error("Failed to connect to MT5. Exiting.")
            sys.exit(1)

        account = get_account_info()
        log.info(f"Account balance: ${account.get('balance', 0):,.2f}")
        log.info(f"Markets: {len(settings.SYMBOLS)} symbols")
        log.info(f"Schedule: Scans at UTC {settings.SCAN_TIMES_UTC}")
        log.info(f"Risk: A+={settings.RISK_PER_TRADE['A+']*100}% | "
                 f"A={settings.RISK_PER_TRADE['A']*100}% | "
                 f"B={settings.RISK_PER_TRADE['B']*100}%")

        # Update starting balance from live account
        self.risk.starting_balance = account.get("balance", settings.WALLET_BALANCE)

        # Start dashboard in background thread
        self._start_dashboard()

        # Main loop
        log.info("Entering main loop. Ctrl+C to stop.")
        try:
            while self.running:
                self._main_loop()
                time.sleep(30)  # Check every 30 seconds
        except KeyboardInterrupt:
            log.info("Shutdown requested")
        finally:
            self._shutdown()

    def _main_loop(self):
        """Main loop: check schedule, manage positions, run scans."""
        now = datetime.now(timezone.utc)

        # Reset daily counters at midnight UTC
        if now.hour == 0 and now.minute < 1:
            self.risk.reset_daily()
            self.scans_today = 0
            self.last_scan_hour = -1

        # Manage existing positions every cycle
        try:
            self.position_mgr.manage_all()
        except Exception as e:
            log.error(f"Position management error: {e}")

        # Check if it's scan time
        if (now.hour in settings.SCAN_TIMES_UTC and
                now.hour != self.last_scan_hour and
                self.scans_today < settings.MAX_SCANS_PER_DAY):

            self.last_scan_hour = now.hour
            self.scans_today += 1
            log.info(f"Scan #{self.scans_today} starting at {now.strftime('%H:%M')} UTC")
            self._run_scan_cycle()

    def _run_scan_cycle(self):
        """Run a complete scan -> sentiment -> brain -> scorer -> risk -> execute cycle."""
        # Check if trading is allowed
        can_trade, reason = self.risk.check_can_trade()
        if not can_trade:
            log.warning(f"Trading blocked: {reason}")
            return

        # Step 1: Scan all symbols
        log.info("--- SCANNER ---")
        candidates = self.scanner.scan_all()
        if not candidates:
            log.info("No candidates found this scan")
            return

        # Step 2: Sentiment analysis
        log.info("--- SENTIMENT ---")
        sentiments = self.sentiment.analyze_batch(candidates)

        # Step 3: Brain decisions
        log.info("--- BRAIN ---")
        decisions = self.brain.decide_batch(candidates, sentiments)
        if not decisions:
            log.info("Brain approved no trades")
            return

        # Step 4: Score trades
        log.info("--- SCORER ---")
        candidates_map = {c["symbol"]: c for c in candidates}
        scored = self.scorer.score_batch(decisions, candidates_map, sentiments)
        if not scored:
            log.info("No trades passed scoring")
            return

        # Limit trades per scan
        scored = scored[:settings.MAX_TRADES_PER_SCAN]

        # Step 5: Risk check and position sizing
        log.info("--- RISK & EXECUTION ---")
        executed = 0
        for decision in scored:
            symbol = decision["symbol"]

            # Check correlation limits
            if not self.risk.check_correlation(symbol):
                log.info(f"Skipping {symbol}: correlation limit")
                continue

            # Re-check if we can still trade
            can_trade, reason = self.risk.check_can_trade()
            if not can_trade:
                log.warning(f"Trading stopped mid-scan: {reason}")
                break

            # Calculate position size
            candidate = candidates_map[symbol]
            order = self.risk.calculate_position_size(decision, candidate)
            if not order:
                log.warning(f"Position sizing failed for {symbol}")
                continue

            # Add grade to order
            order["grade"] = decision["grade"]

            # Execute
            result = self.executor.execute(order)
            if result["success"]:
                self.position_mgr.register_trade(result)
                executed += 1
                log.info(f"Trade #{executed}: {symbol} {order['action']} executed")
            else:
                log.error(f"Execution failed for {symbol}: {result.get('error')}")

        log.info(f"Scan complete: {executed} trades executed")

    def _start_dashboard(self):
        """Start the dashboard in a background thread."""
        try:
            app = create_dashboard(self.risk, self.position_mgr)
            thread = threading.Thread(
                target=app.run,
                kwargs={
                    "host": settings.DASHBOARD_HOST,
                    "port": settings.DASHBOARD_PORT,
                    "debug": False,
                },
                daemon=True,
            )
            thread.start()
            log.info(f"Dashboard running at http://localhost:{settings.DASHBOARD_PORT}")
        except Exception as e:
            log.error(f"Dashboard start failed: {e}")

    def _shutdown(self):
        """Clean shutdown."""
        self.running = False
        log.info("Shutting down CLAWBOT v2...")
        shutdown_mt5()
        log.info("Goodbye.")


if __name__ == "__main__":
    bot = ClawBot()
    bot.start()
