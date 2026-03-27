"""
MT5 Trade Executor for CLAWBOT v2.
Places orders with SL/TP, verifies they're set, retries if broker strips them.
"""
import time
import MetaTrader5 as mt5
from config import settings
from utils.mt5_helper import resolve_symbol, get_symbol_info
from utils.logger import log, get_trade_logger


class Executor:
    def __init__(self):
        self.trade_log = get_trade_logger()

    def execute(self, order: dict) -> dict:
        """Execute a trade order with SL/TP verification."""
        symbol = order["symbol"]
        broker_symbol = resolve_symbol(symbol)
        if not broker_symbol:
            return {"success": False, "error": f"Symbol not found: {symbol}"}

        sym_info = get_symbol_info(symbol)
        if not sym_info:
            return {"success": False, "error": f"No symbol info: {symbol}"}

        # Determine filling mode
        filling_type = self._get_filling_type(sym_info)

        # Build order request
        order_type = mt5.ORDER_TYPE_BUY if order["action"] == "BUY" else mt5.ORDER_TYPE_SELL
        price = sym_info["ask"] if order["action"] == "BUY" else sym_info["bid"]

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": order["lot_size"],
            "type": order_type,
            "price": price,
            "sl": order["sl_price"],
            "tp": order["tp_price"],
            "deviation": settings.SLIPPAGE_POINTS,
            "magic": 202603,
            "comment": f"CLAW_{order.get('grade', 'B')}_{symbol}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }

        log.info(
            f"Executing | {symbol} {order['action']} | Lot: {order['lot_size']} | "
            f"Price: {price} | SL: {order['sl_price']} | TP: {order['tp_price']}"
        )

        # Send order
        result = mt5.order_send(request)

        if result is None:
            error = mt5.last_error()
            log.error(f"Order send returned None: {error}")
            return {"success": False, "error": str(error)}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            log.error(f"Order failed: {result.retcode} - {result.comment}")
            return {
                "success": False,
                "error": f"Retcode {result.retcode}: {result.comment}",
                "retcode": result.retcode,
            }

        ticket = result.order
        log.info(f"Order filled | Ticket: {ticket} | Price: {result.price}")

        # Verify and retry SL/TP if broker stripped them
        sl_tp_ok = self._verify_sl_tp(ticket, order["sl_price"], order["tp_price"])

        trade_result = {
            "success": True,
            "ticket": ticket,
            "symbol": broker_symbol,
            "action": order["action"],
            "lot_size": order["lot_size"],
            "fill_price": result.price,
            "sl_price": order["sl_price"],
            "tp_price": order["tp_price"],
            "sl_tp_verified": sl_tp_ok,
            "grade": order.get("grade", "B"),
            "risk_amount": order.get("risk_amount", 0),
        }

        # Log trade
        self.trade_log.info(
            f"OPEN | {symbol} {order['action']} | Ticket: {ticket} | "
            f"Lot: {order['lot_size']} | Price: {result.price} | "
            f"SL: {order['sl_price']} | TP: {order['tp_price']} | "
            f"Grade: {order.get('grade', 'B')} | Risk: ${order.get('risk_amount', 0):.2f}"
        )

        return trade_result

    def _verify_sl_tp(self, ticket: int, sl: float, tp: float) -> bool:
        """Verify SL/TP are set on the position, retry if not."""
        for attempt in range(settings.SL_TP_RETRY_ATTEMPTS):
            time.sleep(settings.SL_TP_RETRY_DELAY)

            # Get the position
            position = mt5.positions_get(ticket=ticket)
            if not position:
                log.warning(f"Position {ticket} not found for SL/TP check")
                continue

            pos = position[0]
            sl_set = abs(pos.sl - sl) < 0.01 if sl > 0 else True
            tp_set = abs(pos.tp - tp) < 0.01 if tp > 0 else True

            if sl_set and tp_set:
                log.info(f"SL/TP verified on ticket {ticket}")
                return True

            # Retry setting SL/TP
            log.warning(
                f"SL/TP missing on {ticket} (attempt {attempt + 1}) | "
                f"Expected SL={sl}, Got={pos.sl} | Expected TP={tp}, Got={pos.tp}"
            )

            modify_request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": sl,
                "tp": tp,
            }

            modify_result = mt5.order_send(modify_request)
            if modify_result and modify_result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f"SL/TP set on retry {attempt + 1} for ticket {ticket}")
                return True
            else:
                log.warning(f"SL/TP retry {attempt + 1} failed: {modify_result}")

        log.error(f"Failed to set SL/TP after {settings.SL_TP_RETRY_ATTEMPTS} attempts on {ticket}")
        return False

    def _get_filling_type(self, sym_info: dict):
        """Determine the correct filling type for the symbol."""
        filling = sym_info.get("filling_mode", 0)

        # Try FOK first (Markets.com default)
        if settings.FILLING_MODE == "FOK":
            return mt5.ORDER_FILLING_FOK

        if filling & mt5.ORDER_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        elif filling & mt5.ORDER_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def close_position(self, ticket: int, comment: str = "CLAW_CLOSE") -> bool:
        """Close a specific position by ticket."""
        position = mt5.positions_get(ticket=ticket)
        if not position:
            log.warning(f"Position {ticket} not found for close")
            return False

        pos = position[0]
        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol)

        if price is None:
            log.error(f"No tick for {pos.symbol}")
            return False

        close_price = price.bid if pos.type == mt5.ORDER_TYPE_BUY else price.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": settings.SLIPPAGE_POINTS,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"Closed position {ticket} | {pos.symbol} | P&L: {pos.profit}")
            self.trade_log.info(
                f"CLOSE | {pos.symbol} | Ticket: {ticket} | "
                f"P&L: {pos.profit} | Reason: {comment}"
            )
            return True

        log.error(f"Close failed for {ticket}: {result}")
        return False

    def partial_close(self, ticket: int, ratio: float, comment: str = "CLAW_TP1") -> bool:
        """Partially close a position (e.g., 50% at TP1)."""
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return False

        pos = position[0]
        close_volume = round(pos.volume * ratio, 2)

        sym_info = mt5.symbol_info(pos.symbol)
        if sym_info:
            close_volume = max(sym_info.volume_min, close_volume)
            close_volume = round(close_volume / sym_info.volume_step) * sym_info.volume_step
            close_volume = round(close_volume, 2)

        if close_volume >= pos.volume:
            return self.close_position(ticket, comment)

        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol)
        if not price:
            return False

        close_price = price.bid if pos.type == mt5.ORDER_TYPE_BUY else price.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": close_volume,
            "type": order_type,
            "position": ticket,
            "price": close_price,
            "deviation": settings.SLIPPAGE_POINTS,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"Partial close {ticket} | {close_volume} lots | {comment}")
            self.trade_log.info(
                f"PARTIAL | {pos.symbol} | Ticket: {ticket} | "
                f"Closed: {close_volume}/{pos.volume} lots | Reason: {comment}"
            )
            return True

        log.error(f"Partial close failed for {ticket}: {result}")
        return False
