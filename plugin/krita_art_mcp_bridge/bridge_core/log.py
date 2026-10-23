import logging
import logging.handlers
from pathlib import Path

from . import paths

NAME = "krita_art_mcp_bridge"
MAX_BYTES = 5 * 1024 * 1024


class _RedactingFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self.secret = ""

    def format(self, record: logging.LogRecord) -> str:
        # Redacts the finished text, so a token inside a traceback is caught too.
        text = super().format(record)
        return text.replace(self.secret, "[token]") if self.secret else text


def setup(log_dir: Path) -> logging.Logger:
    paths.private_dir(log_dir)
    logger = logging.getLogger(NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for old in list(logger.handlers):
        logger.removeHandler(old)
        old.close()
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "plugin.log", maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(_RedactingFormatter())
    logger.addHandler(handler)
    return logger


def redact(logger: logging.Logger, secret: str) -> None:
    for handler in logger.handlers:
        if isinstance(handler.formatter, _RedactingFormatter):
            handler.formatter.secret = secret
