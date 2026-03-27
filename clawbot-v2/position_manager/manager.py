"""
Position Manager for CLAWBOT v2.
Handles trailing stops, breakeven moves, TP1 partial closes,
external close detection, and force-close fallback when SL/TP
don't trigger on the broker side.
"""
import time
import MetaTrader5 as mt5
from config import settings
from utils.mt5_helper import get_open_positions
from utils.logger import log, get_trade_logger
from executor.mt5_executor import Executor


class PositionManager:
    def __init__(self):
        self.executor = Executor()
        self.trade_log = get_trade_logger()
        # Track managed positions: {ticket: position_data}
        self.managed = {}

    def register_trade(self, trade_result: dict):
        """Register a new trade for management."""
        ticket = trade_result["ticket"]
        self.managed[ticket] = {
            "ticket": ticket,
            "symbol": trade_result["symbol"],
            "action": trade_result["action"],
            "entry_price": trade_result["fill_price"],
            "sl_price": trade_result["sl_price"],
            "tp_price": trade_result["tp_price"],
            "original_sl": trade_result["sl_price"],
            "lot_size": trade_result["lot_size"],
            "risk_amount": trade_result.get("risk_amount", 0),
            "breakeven_done": False,
            "tp1_done": False,
            "trailing_active": False,
        }
        log.info(f"Position registered: {trade_result['symbol']} #{ticket}")

    def manage_all(self):
        """Run one management cycle for all tracked positions."""
        if not self.managed:
            return

        # Get current open positions from broker
        open_positions = get_open_positions()
        open_tickets = {p["ticket"] for p in open_positions}

        # Detect externally closed positions
        closed_tickets = []
        for ticket in list(self.managed.keys()):
            if ticket not in open_tickets:
                info = self.managed[ticket]
                log.info(
                    f"External close detected: {info['symbol']} #{ticket}"
                )
                self.trade_log.info(
                    f"EXT_CLOSE | {info['symbol']} | Ticket: {ticket}"
                )
                closed_tickets.append(ticket)

        for ticket in closed_tickets:
            del self.managed[ticket]

        # Manage each open position
        for pos_data in open_positions:
            ticket = pos_data["ticket"]
            if ticket not in self.managed:
                continue

            managed = self.managed[ticket]

            # Force-close check: if price has breached SL/TP but broker hasn't closed
            self._check_force_close(pos_data, managed)

            # Calculate R-multiple (how many R's of profit)
            r_multiple = self._calc_r_multiple(pos_data, managed)

            # 1. Breakeven at 1R
            if not managed["breakeven_done"] and r_multiple >= settings.BREAKEVEN_ACTIVATION_R:
                self._move_to_breakeven(pos_data, managed)

            # 2. TP1 partial close at 2R
            if not managed["tp1_done"] and r_multiple >= settings.TP1_R_TARGET:
                self._execute_tp1(pos_data, managed)

            # 3. Trailing stop at 1.5R+
            if r_multiple >= settings.TRAILING_STOP_ACTIVATION_R:
                self._update_trailing_stop(pos_data, managed)

    def _calc_r_multiple(self, pos_data: dict, managed: dict) -> float:
        """Calculate current R-multiple (profit in terms of initial risk)."""
        entry = managed["entry_price"]
        sl = managed["original_sl"]
        current = pos_data["current_price"]

        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            return 0.0

        if managed["action"] == "BUY":
            profit_distance = current - entry
        else:
            profit_distance = entry - current

        return profit_distance / risk_distance

    def _check_force_close(self, pos_data: dict, managed: dict):
        """Force-close if price has breached SL or TP but broker hasn't acted."""
        current = pos_data["current_price"]
        sl = pos_data["sl"]
        tp = pos_data["tp"]
        ticket = pos_data["ticket"]

        if sl <= 0 and tp <= 0:
            return

        should_close = False
        reason = ""

        if managed["action"] == "BUY":
            if sl > 0 and current <= sl:
                should_close = True
                reason = f"FORCE_SL (price {current} <= SL {sl})"
            elif tp > 0 and current >= tp:
                should_close = True
                reason = f"FORCE_TP (price {current} >= TP {tp})"
        else:
            if sl > 0 and current >= sl:
                should_close = True
                reason = f"FORCE_SL (price {current} >= SL {sl})"
            elif tp > 0 and current <= tp:
                should_close = True
                reason = f"FORCE_TP (price {current} <= TP {tp})"

        if should_close:
            log.warning(f"Force close: {managed['symbol']} #{ticket} | {reason}")
            self.executor.close_position(ticket, f"CLAW_{reason[:20]}")
            if ticket in self.managed:
                del self.managed[ticket]

    def _move_to_breakeven(self, pos_data: dict, managed: dict):
        """Move SL to breakeven (entry price + small buffer)."""
        ticket = pos_data["ticket"]
        entry = managed["entry_price"]
        symbol = pos_data["symbol"]

        # Add small buffer (1 point) above entry
        info = mt5.symbol_info(symbol)
        buffer = info.point * 5 if info else 0

        if managed["action"] == "BUY":
            new_sl = entry + buffer
        else:
            new_sl = entry - buffer

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": round(new_sl, info.digits if info else 5),
            "tp": pos_data["tp"],
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            managed["breakeven_done"] = True
            managed["sl_price"] = new_sl
            log.info(f"Breakeven set: {managed['symbol']} #{ticket} | SL -> {new_sl}")
        else:
            log.warning(f"Breakeven failed for {ticket}: {result}")

    def _execute_tp1(self, pos_data: dict, managed: dict):
        """Close partial position at TP1."""
        ticket = pos_data["ticket"]
        success = self.executor.partial_close(
            ticket,
            ratio=settings.TP1_RATIO,
            comment="CLAW_TP1"
        )
        if success:
            managed["tp1_done"] = True
            log.info(
                f"TP1 hit: {managed['symbol']} #{ticket} | "
                f"Closed {settings.TP1_RATIO*100:.0f}%"
            )

    def _update_trailing_stop(self, pos_data: dict, managed: dict):
        """Update trailing stop based on R-multiple distance."""
        ticket = pos_data["ticket"]
        entry = managed["entry_price"]
        sl = managed["original_sl"]
        current = pos_data["current_price"]
        symbol = pos_data["symbol"]

        risk_distance = abs(entry - sl)
        trail_distance = risk_distance * settings.TRAILING_STOP_DISTANCE_R

        if managed["action"] == "BUY":
            new_sl = current - trail_distance
            # Only move SL up, never down
            if new_sl <= managed["sl_price"]:
                return
        else:
            new_sl = current + trail_distance
            # Only move SL down, never up
            if new_sl >= managed["sl_price"]:
                return

        info = mt5.symbol_info(symbol)
        digits = info.digits if info else 5

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": round(new_sl, digits),
            "tp": pos_data["tp"],
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            managed["sl_price"] = new_sl
            managed["trailing_active"] = True
            r_mult = self._calc_r_multiple(pos_data, managed)
            log.info(
                f"Trail updated: {managed['symbol']} #{ticket} | "
                f"SL -> {new_sl:.{digits}f} | R: {r_mult:.1f}"
            )

    def get_status(self) -> list:
        """Get status of all managed positions for dashboard."""
        status = []
        open_positions = get_open_positions()
        open_map = {p["ticket"]: p for p in open_positions}

        for ticket, managed in self.managed.items():
            pos = open_map.get(ticket)
            if not pos:
                continue

            r_mult = self._calc_r_multiple(pos, managed)
            status.append({
                "ticket": ticket,
                "symbol": managed["symbol"],
                "action": managed["action"],
                "entry": managed["entry_price"],
                "current": pos["current_price"],
                "sl": pos["sl"],
                "tp": pos["tp"],
                "pnl": pos["profit"],
                "r_multiple": r_mult,
                "breakeven": managed["breakeven_done"],
                "tp1_done": managed["tp1_done"],
                "trailing": managed["trailing_active"],
                "lot_size": pos["volume"],
            })

        return status
