import logging
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

        fh = logging.FileHandler("log.txt", encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

        if settings.LOG_TO_CONSOLE:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            root.addHandler(ch)

        _configured = True

    return logging.getLogger(name)
