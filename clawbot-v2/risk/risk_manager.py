"""
Risk Manager for CLAWBOT v2.
Handles position sizing, recovery mode, daily loss limits, and kill switch.
"""
import MetaTrader5 as mt5
from config import settings
from utils.mt5_helper import get_account_info, get_open_positions, get_symbol_info
from utils.logger import log


class RiskManager:
    def __init__(self):
        self.starting_balance = settings.WALLET_BALANCE
        self.recovery_mode = False
        self.killed = False
        self.daily_pnl = 0.0

    def check_can_trade(self) -> tuple:
        """Check if trading is allowed. Returns (allowed, reason)."""
        if self.killed:
            return False, "Kill switch active - daily loss limit hit"

        account = get_account_info()
        if not account:
            return False, "Cannot get account info"

        balance = account["balance"]
        daily_change = (balance - self.starting_balance) / self.starting_balance

        # Hard kill at -5%
        if daily_change <= -settings.MAX_DAILY_LOSS_PCT:
            self.killed = True
            log.error(
                f"KILL SWITCH | Balance: ${balance:.2f} | "
                f"Loss: {daily_change*100:.1f}% | Closing all positions"
            )
            self._close_all_positions()
            return False, f"Kill switch: {daily_change*100:.1f}% daily loss"

        # Recovery mode at -2%
        if daily_change <= -settings.RECOVERY_TRIGGER_PCT:
            if not self.recovery_mode:
                log.warning(f"RECOVERY MODE ON | Loss: {daily_change*100:.1f}%")
                self.recovery_mode = True
        elif self.recovery_mode and daily_change >= 0:
            log.info("RECOVERY MODE OFF | Back to profit")
            self.recovery_mode = False

        # Check open position count
        positions = get_open_positions()
        if len(positions) >= settings.MAX_OPEN_POSITIONS:
            return False, f"Max open positions ({settings.MAX_OPEN_POSITIONS}) reached"

        self.daily_pnl = daily_change
        return True, "OK"

    def calculate_position_size(self, decision: dict, candidate: dict) -> dict:
        """Calculate position size based on grade, risk rules, and SL distance."""
        account = get_account_info()
        if not account:
            return None

        balance = account["balance"]
        grade = decision.get("grade", "B")
        symbol = decision["symbol"]
        action = decision["action"]

        # Get risk percentage for grade
        risk_pct = settings.RISK_PER_TRADE.get(grade, 0.005)

        # Halve risk in recovery mode
        if self.recovery_mode:
            risk_pct *= settings.RECOVERY_RISK_MULTIPLIER
            log.info(f"Recovery mode: risk reduced to {risk_pct*100:.2f}%")

        risk_amount = balance * risk_pct

        # Calculate SL distance in price
        atr_value = candidate.get("atr_value", 0)
        sl_atr_mult = decision.get("sl_distance_atr", 1.5)
        sl_distance = atr_value * sl_atr_mult

        if sl_distance <= 0:
            log.error(f"Invalid SL distance for {symbol}")
            return None

        # Get symbol info for lot calculation
        sym_info = get_symbol_info(symbol)
        if not sym_info:
            return None

        point = sym_info["point"]
        min_lot = sym_info["min_lot"]
        lot_step = sym_info["lot_step"]

        # Calculate entry, SL, TP prices
        entry_price = sym_info["ask"] if action == "BUY" else sym_info["bid"]

        if action == "BUY":
            sl_price = entry_price - sl_distance
            tp_distance = atr_value * decision.get("tp_distance_atr", 3.0)
            tp_price = entry_price + tp_distance
        else:
            sl_price = entry_price + sl_distance
            tp_distance = atr_value * decision.get("tp_distance_atr", 3.0)
            tp_price = entry_price - tp_distance

        # Calculate lot size: risk_amount / (sl_distance / point) / point_value
        sl_points = sl_distance / point
        if sl_points <= 0:
            return None

        # Approximate lot size (simplified - works for most instruments)
        lot_size = risk_amount / sl_distance

        # For forex/metals, adjust by contract size
        if "USD" in symbol or "XAG" in symbol:
            contract_size = 100000  # Standard forex lot
            if "XAG" in symbol:
                contract_size = 5000  # Silver
            lot_size = risk_amount / (sl_distance * contract_size)

        # Round to lot step
        lot_size = max(min_lot, round(lot_size / lot_step) * lot_step)
        lot_size = round(lot_size, 2)

        # Ensure we don't exceed max lot
        lot_size = min(lot_size, sym_info["max_lot"])

        # Round SL/TP to proper digits
        digits = sym_info["digits"]
        sl_price = round(sl_price, digits)
        tp_price = round(tp_price, digits)
        entry_price = round(entry_price, digits)

        result = {
            "symbol": symbol,
            "action": action,
            "lot_size": lot_size,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_distance": sl_distance,
            "tp_distance": tp_distance,
            "risk_amount": risk_amount,
            "risk_pct": risk_pct,
            "grade": grade,
            "rr_ratio": tp_distance / sl_distance if sl_distance > 0 else 0,
        }

        log.info(
            f"Risk | {symbol} {action} | Lot: {lot_size} | "
            f"Entry: {entry_price} | SL: {sl_price} | TP: {tp_price} | "
            f"Risk: ${risk_amount:.2f} ({risk_pct*100:.1f}%) | RR: 1:{result['rr_ratio']:.1f}"
        )

        return result

    def check_correlation(self, symbol: str) -> bool:
        """Check if adding this symbol would exceed sector correlation limits."""
        positions = get_open_positions()

        # Simple sector grouping
        sectors = {
            "utilities": ["NEE", "AEP", "ED"],
            "water": ["AWK"],
            "waste": ["WM", "RSG"],
            "healthcare": ["HCA", "ACHC", "SCI"],
            "consumer": ["KR"],
            "reit": ["EXR", "NHI"],
            "tech": ["CNS"],
            "metals": ["XAGUSD"],
        }

        # Find which sector our symbol belongs to
        target_sector = None
        for sector, syms in sectors.items():
            if symbol in syms:
                target_sector = sector
                break

        if target_sector is None:
            return True

        # Count positions in same sector
        sector_count = 0
        sector_symbols = sectors.get(target_sector, [])
        for pos in positions:
            for sym in sector_symbols:
                if sym in pos["symbol"]:
                    sector_count += 1

        if sector_count >= settings.MAX_CORRELATION_EXPOSURE:
            log.warning(f"Correlation limit: {sector_count} positions in {target_sector}")
            return False

        return True

    def _close_all_positions(self):
        """Emergency close all positions (kill switch)."""
        positions = get_open_positions()
        for pos in positions:
            try:
                order_type = mt5.ORDER_TYPE_SELL if pos["type"] == "BUY" else mt5.ORDER_TYPE_BUY
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos["symbol"],
                    "volume": pos["volume"],
                    "type": order_type,
                    "position": pos["ticket"],
                    "deviation": settings.SLIPPAGE_POINTS,
                    "comment": "CLAWBOT_KILL",
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    log.info(f"Kill closed: {pos['symbol']} #{pos['ticket']}")
                else:
                    log.error(f"Kill close failed: {pos['symbol']} - {result}")
            except Exception as e:
                log.error(f"Kill close error: {pos['symbol']} - {e}")

    def reset_daily(self):
        """Reset daily counters (call at start of new trading day)."""
        account = get_account_info()
        if account:
            self.starting_balance = account["balance"]
        self.recovery_mode = False
        self.killed = False
        self.daily_pnl = 0.0
        log.info(f"Daily reset | Starting balance: ${self.starting_balance:.2f}")

    def get_status(self) -> dict:
        """Get current risk status for dashboard."""
        account = get_account_info()
        balance = account.get("balance", 0) if account else 0
        daily_change = (balance - self.starting_balance) / self.starting_balance if self.starting_balance > 0 else 0

        return {
            "balance": balance,
            "equity": account.get("equity", 0) if account else 0,
            "starting_balance": self.starting_balance,
            "daily_pnl_pct": daily_change * 100,
            "daily_pnl_usd": balance - self.starting_balance,
            "recovery_mode": self.recovery_mode,
            "killed": self.killed,
            "open_positions": len(get_open_positions()),
        }
