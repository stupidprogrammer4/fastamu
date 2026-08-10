"""Application logging — readable in a terminal, parseable in a log store.

One switch (`logging.format`) picks between the two: `console` gives Rich
tracebacks while you develop, `json` emits one ECS-shaped object per line for
whatever ships your logs. The fields are the same either way, so a message does
not have to be rewritten when it reaches production.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import orjson
from rich.logging import RichHandler

from src.core.config import get_settings

#: Per-task correlation id; set by middleware, surfaced on every record.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """One ECS-shaped JSON object per record.

    The field names are Elastic Common Schema (`log.level`, `service.name`,
    `error.stack_trace`, …) so the output drops into an ES/Kibana pipeline with
    no ingest-side mapping. Anything extra a caller attached to the record
    (`logger.info("...", extra={"order_id": 7})`) is carried through as its own
    field rather than being flattened into the message.
    """

    BUILTIN_RECORD_ATTRS = frozenset(
        {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message", "module",
            "msecs", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "request_id", "stack_info", "stacklevel",
            "taskName", "thread", "threadName",
        }
    )

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "@timestamp": self._timestamp(record.created),
            "log.level": record.levelname.lower(),
            "log.logger": record.name,
            "log.origin.file.name": record.filename,
            "log.origin.file.line": record.lineno,
            "log.origin.function": record.funcName,
            "service.name": self.service,
            "process.thread.name": record.threadName,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["error.type"] = getattr(exc_type, "__name__", None)
            payload["error.message"] = str(exc_value)
            payload["error.stack_trace"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["error.stack_trace"] = record.exc_text

        if record.stack_info:
            payload["log.origin.stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in self.BUILTIN_RECORD_ATTRS:
                payload[key] = value

        # default=str: a log line must never fail on an unserialisable value
        return orjson.dumps(payload, default=str).decode()

    @staticmethod
    def _timestamp(created: float) -> str:
        stamp = datetime.fromtimestamp(created, UTC)
        return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Logger:
    """The app logger, and the owner of the root handler.

    `setup` installs one handler on the **root** logger and makes uvicorn,
    gunicorn and taskiq propagate into it, so a request line from the server and
    a line from a service look alike and carry the same request id — otherwise
    half the output is formatted by somebody else's defaults.
    """

    #: Loggers whose own handlers are dropped so their records reach ours.
    ADOPTED_LOGGERS = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "gunicorn.error",
        "gunicorn.access",
        "taskiq",
    )

    def __init__(self, name: str = "app", level: int | str = logging.INFO) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)

    def setup(self) -> None:
        """Install the configured handler on the root logger and adopt the
        third-party loggers."""
        config = get_settings().logging
        handler = self.build_handler(config.format, config.service)

        root = logging.getLogger()
        for existing in list(root.handlers):
            root.removeHandler(existing)
        root.addHandler(handler)
        root.setLevel(config.level)

        for name in self.ADOPTED_LOGGERS:
            adopted = logging.getLogger(name)
            adopted.handlers.clear()
            adopted.propagate = True

        self.set_level(config.level)

    @staticmethod
    def build_handler(fmt: str, service: str) -> logging.Handler:
        handler: logging.Handler
        if fmt == "json":
            handler = logging.StreamHandler()
            handler.setFormatter(JSONFormatter(service))
        else:
            handler = RichHandler(rich_tracebacks=True, show_path=False)
            handler.setFormatter(logging.Formatter("[%(request_id)s] %(message)s"))
        handler.addFilter(_ContextFilter())
        return handler

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


logger: Logger = Logger(name="app")
logger.setup()
