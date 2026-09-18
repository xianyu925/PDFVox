import logging
from pathlib import Path

from app.config import settings

_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured

    if not _configured:
        level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        root = logging.getLogger()
        root.setLevel(level)

        if settings.LOG_TO_FILE:
            log_path = Path(settings.LOG_FILE)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)

        if settings.LOG_TO_CONSOLE:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            root.addHandler(ch)

        _configured = True

    return logging.getLogger(name)
