"""
Shared helpers used across the pipeline.
"""

import logging
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a readable format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def ensure_dir(path: Path) -> Path:
    """Create *path* (and parents) if it doesn't exist, then return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, max_len: int = 80) -> str:
    """
    Turn an arbitrary string (e.g. video title) into a filesystem-safe name.
    Keeps alphanumerics, spaces, hyphens, and underscores.
    """
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    cleaned = "_".join(cleaned.split())  # collapse whitespace
    return cleaned[:max_len] if cleaned else "untitled"


def format_number(n: int | float | None) -> str:
    """Format a number with commas, or return 'N/A'."""
    if n is None:
        return "N/A"
    return f"{int(n):,}"
