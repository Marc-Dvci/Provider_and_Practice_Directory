"""Logging setup for the pipeline.

A single ``configure_logging`` call wires up a concise, timestamped formatter.
Library code never configures logging on import; only the CLI / dashboard / tests
call ``configure_logging`` so that importing the package stays side-effect free.
"""

from __future__ import annotations

import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str | int | None = None) -> None:
    """Configure root logging once, idempotently.

    Level resolution order: explicit ``level`` arg, then ``DIRPIPE_LOG_LEVEL``
    env var, then ``INFO``.
    """
    if level is None:
        level = os.environ.get("DIRPIPE_LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
        root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger (``directory_pipeline.<name>``)."""
    return logging.getLogger(f"directory_pipeline.{name}")
