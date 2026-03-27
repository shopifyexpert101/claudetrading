"""
Logging utility for CLAWBOT v2.
Clean console + file logging with no unicode issues.
"""
import logging
import os
from datetime import datetime
from config import settings


def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    """Create a logger with console and optional file output."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    if log_file:
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(settings.LOG_DIR, log_file),
            encoding="utf-8"
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def get_trade_logger() -> logging.Logger:
    """Logger specifically for trade records."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return setup_logger("trades", f"trades_{today}.log")


log = setup_logger("clawbot", "clawbot.log")
