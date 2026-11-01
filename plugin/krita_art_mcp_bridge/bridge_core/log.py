import logging
import logging.handlers
import os
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
    path = log_dir / "plugin.log"
    _private_file(str(path))
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8"
    )
    # Rotation starts a new file, which must be private too.
    handler.rotator = _rotate
    handler.setFormatter(_RedactingFormatter())
    logger.addHandler(handler)
    return logger


def _private_file(path: str) -> None:
    # Sets the mode only on a new file; the data folder's 0700 guards one made any other way.
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))


def _rotate(source: str, dest: str) -> None:
    # Like the default rotator, a log deleted meanwhile is simply started afresh.
    if os.path.exists(source):
        os.replace(source, dest)
    _private_file(source)


def redact(logger: logging.Logger, secret: str) -> None:
    for handler in logger.handlers:
        if isinstance(handler.formatter, _RedactingFormatter):
            handler.formatter.secret = secret
