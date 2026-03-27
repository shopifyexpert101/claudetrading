"""
CLAWBOT v2 Configuration
All settings for the trading system.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ───────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ─── AI Models ──────────────────────────────────────────────
BRAIN_MODEL = "claude-opus-4-6"
SCORER_MODEL = "claude-sonnet-4-5"
SENTIMENT_MODEL = "claude-haiku-4-5-20251001"

# ─── MT5 Connection ─────────────────────────────────────────
MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", "10010260785"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "MetaQuotes-Demo")
MT5_PATH = os.getenv("MT5_PATH", "")

# ─── Markets ────────────────────────────────────────────────
# 14 defensive/recession-proof stocks + silver
SYMBOLS = [
    "NEE", "AEP", "ED",       # Utilities
    "AWK",                      # Water
    "WM", "RSG",               # Waste management
    "SCI",                      # Death care
    "HCA", "ACHC",             # Healthcare
    "KR",                       # Grocery
    "EXR",                      # Storage REIT
    "NHI", "CNS",              # Healthcare REIT / IT services
    "XAGUSD",                  # Silver
]

# Symbol mapping for Markets.com naming conventions
# Maps our symbol names to broker-specific names
SYMBOL_MAP = {
    "NEE": "NEE", "AEP": "AEP", "ED": "ED", "AWK": "AWK",
    "WM": "WM", "RSG": "RSG", "SCI": "SCI", "HCA": "HCA",
    "ACHC": "ACHC", "KR": "KR", "EXR": "EXR", "NHI": "NHI",
    "CNS": "CNS", "XAGUSD": "XAGUSD",
}

# ─── Schedule ───────────────────────────────────────────────
SCAN_TIMES_UTC = [14, 16, 18, 20]  # 6pm-midnight Dubai
SCAN_INTERVAL_SECONDS = 30         # Main loop check interval
MAX_SCANS_PER_DAY = 4
MAX_TRADES_PER_SCAN = 4

# ─── Scanner Filters ───────────────────────────────────────
SCANNER_TIMEFRAMES = ["H1", "H4"]
ATR_PERIOD = 14
ATR_EXPANSION_RATIO = 0.85       # Loose for defensive stocks
VOLUME_ZSCORE_MIN = -0.5         # Loose for low-vol stocks
MIN_BARS_REQUIRED = 100

# ─── Scoring ────────────────────────────────────────────────
SCORE_MIN = 60                    # Minimum score to trade

# Session multipliers (UTC hours)
SESSION_MULTIPLIERS = {
    "london": {"start": 8, "end": 16, "multiplier": 1.1},
    "new_york": {"start": 13, "end": 21, "multiplier": 1.15},
    "overlap": {"start": 13, "end": 16, "multiplier": 1.2},
    "asia": {"start": 0, "end": 8, "multiplier": 0.9},
}

# ─── Risk Management ───────────────────────────────────────
WALLET_BALANCE = 4875.0           # Updated after Day 1

# Position sizing by grade
RISK_PER_TRADE = {
    "A+": 0.015,  # 1.5%
    "A":  0.010,  # 1.0%
    "B":  0.005,  # 0.5%
}

MAX_DAILY_LOSS_PCT = 0.05         # -5% hard kill
RECOVERY_TRIGGER_PCT = 0.02       # -2% enters recovery mode
RECOVERY_RISK_MULTIPLIER = 0.5    # Halve risk in recovery

MAX_OPEN_POSITIONS = 6
MAX_CORRELATION_EXPOSURE = 3      # Max positions in same sector

# ─── Execution ──────────────────────────────────────────────
SL_TP_RETRY_ATTEMPTS = 3
SL_TP_RETRY_DELAY = 2.0          # seconds
ORDER_TIMEOUT = 30                # seconds
SLIPPAGE_POINTS = 20
FILLING_MODE = "FOK"             # Fill or Kill (Markets.com)

# ─── Position Manager ──────────────────────────────────────
TRAILING_STOP_ACTIVATION_R = 1.5  # Activate at 1.5R profit
TRAILING_STOP_DISTANCE_R = 0.5    # Trail 0.5R behind
BREAKEVEN_ACTIVATION_R = 1.0      # Move to breakeven at 1R
TP1_RATIO = 0.5                   # Close 50% at TP1
TP1_R_TARGET = 2.0                # TP1 at 2R
FORCE_CLOSE_CHECK_INTERVAL = 5    # seconds between force-close checks

# ─── Dashboard ──────────────────────────────────────────────
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8050
DASHBOARD_THEME = "dark"

# ─── Logging ────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_DIR = "data/logs"
TRADE_LOG_DIR = "data/trades"

# ─── Brain Settings ────────────────────────────────────────
REGIME_TYPES = ["trending", "ranging", "volatile", "crisis"]
CRISIS_ALPHA_ENABLED = True

# ─── Sentiment ──────────────────────────────────────────────
SENTIMENT_WEB_SEARCH = True
SENTIMENT_FALLBACK = True         # Fall back to model-only if search fails
SENTIMENT_NEVER_BLOCKS = True     # Sentiment informs but never blocks trades
