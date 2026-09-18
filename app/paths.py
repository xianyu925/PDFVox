"""Filesystem locations shared by source and frozen desktop builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "PDFVox"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Return the read-only application resource root."""
    override = os.getenv("PDFVOX_RESOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent


def user_data_root() -> Path:
    """Return a writable per-user directory for the desktop application."""
    override = os.getenv("PDFVOX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return (Path(local_app_data) / APP_NAME).resolve()
    return (Path.home() / f".{APP_NAME.lower()}").resolve()
