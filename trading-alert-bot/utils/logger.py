"""Logging setup for the trading alert bot."""

import logging
import os
from logging.handlers import RotatingFileHandler

import yaml


def setup_logger(name: str = "trading_bot", config_path: str = "config.yaml") -> logging.Logger:
    """Configure and return the application logger."""
    log_cfg = {"level": "INFO", "file": "alerts.log", "max_size_mb": 50, "backup_count": 5}

    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
            log_cfg.update(cfg.get("logging", {}))

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_cfg["level"].upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    fh = RotatingFileHandler(
        log_cfg["file"],
        maxBytes=log_cfg["max_size_mb"] * 1024 * 1024,
        backupCount=log_cfg["backup_count"],
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# Module-level default logger
logger = setup_logger()
