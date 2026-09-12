from __future__ import annotations

import time
from contextvars import ContextVar, Token

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from fastamu.core.logger import logger, request_id_ctx


class LoggingMiddleware(TaskiqMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._execution: ContextVar[tuple[float, Token] | None] = ContextVar(
            "scheduler_execution", default=None
        )

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        logger.info("--> enqueue %s id=%s", message.task_name, message.task_id)
        return message

    def post_send(self, message: TaskiqMessage) -> None:
        logger.info(
            "<-- enqueued %s id=%s", message.task_name, message.task_id
        )

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        self._execution.set(
            (time.perf_counter(), request_id_ctx.set(message.task_id))
        )
        logger.info("--> exec %s id=%s", message.task_name, message.task_id)
        return message

    def post_execute(
        self, message: TaskiqMessage, result: TaskiqResult
    ) -> None:
        elapsed_ms = self._elapsed_ms()
        logger.info(
            "<-- exec %s id=%s %s %.2fms",
            message.task_name,
            message.task_id,
            "err" if result.is_err else "ok",
            elapsed_ms,
        )
        self._reset()

    def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        exception: BaseException,
    ) -> None:
        elapsed_ms = self._elapsed_ms()
        logger.error(
            "<-- exec %s id=%s failed after %.2fms: %s",
            message.task_name,
            message.task_id,
            elapsed_ms,
            exception,
            exc_info=exception,
        )
        self._reset()

    def _elapsed_ms(self) -> float:
        execution = self._execution.get()
        elapsed = 0.0
        if execution is not None:
            elapsed = (time.perf_counter() - execution[0]) * 1000
        return elapsed

    def _reset(self) -> None:
        execution = self._execution.get()
        if execution is not None:
            request_id_ctx.reset(execution[1])
            self._execution.set(None)
