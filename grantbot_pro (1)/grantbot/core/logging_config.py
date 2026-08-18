from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from grantbot.core.config import settings


_CONFIGURED = False


def configure_logging() -> logging.Logger:
    global _CONFIGURED

    logger = logging.getLogger("grantbot")

    if _CONFIGURED:
        return logger

    level = getattr(
        logging,
        settings.log_level,
        logging.INFO,
    )

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    logfile = settings.log_dir / "grantbot.log"

    rotating = RotatingFileHandler(
        logfile,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )

    rotating.setLevel(level)
    rotating.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(rotating)

    _CONFIGURED = True

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    root = configure_logging()

    if not name:
        return root

    return root.getChild(name)
