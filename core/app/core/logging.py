import logging
import os
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.fchmod(stream.fileno(), 0o600)
        return stream

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = len((self.format(record) + "\n").encode("utf-8"))
        return self.maxBytes > 0 and self.stream.tell() + size >= self.maxBytes


@contextmanager
def local_logging():
    directory = Path(settings.log_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "shade.log"
    handler = PrivateRotatingHandler(
        path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    path.chmod(0o600)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger = logging.getLogger("shade")
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
