"""Per-dialog-type log routing via ContextVar."""
import logging
import threading
from contextvars import ContextVar
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

current_dialog_type: ContextVar[str] = ContextVar("current_dialog_type", default="default")


class PerTypeFileHandler(logging.Handler):
    """Routes log records into logs/<dialog_type>/<filename>, creating subdirs lazily."""

    def __init__(
        self,
        filename: str,
        logs_dir: Path,
        when: str = "midnight",
        interval: int = 1,
        backupCount: int = 6,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self._filename = filename
        self._logs_dir = logs_dir
        self._when = when
        self._interval = interval
        self._backupCount = backupCount
        self._encoding = encoding
        self._handlers: dict[str, TimedRotatingFileHandler] = {}
        self._lock = threading.Lock()

    def _get_handler(self, dialog_type: str) -> TimedRotatingFileHandler:
        if dialog_type not in self._handlers:
            with self._lock:
                if dialog_type not in self._handlers:
                    subdir = self._logs_dir / dialog_type
                    subdir.mkdir(parents=True, exist_ok=True)
                    h = TimedRotatingFileHandler(
                        filename=subdir / self._filename,
                        when=self._when,
                        interval=self._interval,
                        backupCount=self._backupCount,
                        encoding=self._encoding,
                        utc=False,
                    )
                    h.suffix = "%Y-%m-%d"
                    h.setFormatter(self.formatter)
                    self._handlers[dialog_type] = h
        return self._handlers[dialog_type]

    def setFormatter(self, fmt: logging.Formatter | None) -> None:
        super().setFormatter(fmt)
        with self._lock:
            for h in self._handlers.values():
                h.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        self._get_handler(current_dialog_type.get()).emit(record)
