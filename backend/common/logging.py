"""Shared logging configuration for the TalaSuri pipeline."""

import logging
import sys


def setup_logging(verbose: bool = False) -> None:
    """Wire up the `backend.*` logger. `verbose=True` selects DEBUG."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger("backend")
    root.setLevel(level)
    root.addHandler(handler)
