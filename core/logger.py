"""
Logging configuration.

- File handler  → logs/pipeline.log  (DEBUG+, plain text, rotated at 5 MB)
- Console handler → WARNING+ only (rich already handles INFO output)

Usage anywhere in the project:
    from core.logger import get_logger
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from core.config import get_config

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    cfg = get_config()
    os.makedirs(os.path.dirname(cfg.LOG_FILE), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File – full detail
    fh = RotatingFileHandler(
        cfg.LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(fh)

    # Console – warnings and above (rich console handles info-level UX)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(ch)

    # Silence noisy third-party loggers
    for noisy in ("aiohttp", "asyncio", "urllib3", "chardet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)