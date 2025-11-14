"""Core package for the AI expense chatbot.

This module bootstraps a consistent logging configuration so every submodule can
retrieve loggers via :func:`get_logger` without repeating handler setup.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_ROOT_LOGGER_NAME = "expense_bot"


def _bootstrap_logging() -> None:
    """Configure the package-wide logger once."""
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    if logger.handlers:
        # Logging already configured elsewhere (e.g., tests), so reuse it.
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(level if level in logging._nameToLevel else "INFO")
    logger.propagate = False


def get_logger(component: Optional[str] = None) -> logging.Logger:
    """Return a child logger scoped under the package root."""
    name = (
        _ROOT_LOGGER_NAME
        if not component
        else f"{_ROOT_LOGGER_NAME}.{component.strip('.')}"
    )
    return logging.getLogger(name)


_bootstrap_logging()

__all__ = ["get_logger"]
