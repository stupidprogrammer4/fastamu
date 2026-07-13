from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from rich.logging import RichHandler

#: Per-task correlation id; set by middleware, surfaced on every record.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


class Logger:

    def __init__(self, name: str = "app", level: int | str = logging.INFO) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.propagate = False

        if not any(isinstance(f, _ContextFilter) for f in self._logger.filters):
            self._logger.addFilter(_ContextFilter())

        if not self._logger.handlers:
            console = RichHandler(rich_tracebacks=True, show_path=False)
            console.setFormatter(logging.Formatter("[%(request_id)s] %(message)s"))
            self.add_handler(console)

    def add_handler(self, handler: logging.Handler) -> None:
        self._logger.addHandler(handler)

    def set_level(self, level: int | str) -> None:
        self._logger.setLevel(level)

    def debug(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.debug(msg, *args, stacklevel=2, **kw)

    def info(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.info(msg, *args, stacklevel=2, **kw)

    def warning(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.warning(msg, *args, stacklevel=2, **kw)

    def error(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.error(msg, *args, stacklevel=2, **kw)

    def exception(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.exception(msg, *args, stacklevel=2, **kw)

    def critical(self, msg: object, *args: Any, **kw: Any) -> None:
        self._logger.critical(msg, *args, stacklevel=2, **kw)



logger: Logger = Logger(
    name="app",
    level=logging.DEBUG,
)
