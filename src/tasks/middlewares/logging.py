from __future__ import annotations

import time

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from src.core.logger import logger, request_id_ctx


class LoggingMiddleware(TaskiqMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._starts: dict[str, float] = {}
        self._tokens: dict[str, object] = {}

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        logger.info("--> enqueue %s id=%s", message.task_name, message.task_id)
        return message

    def post_send(self, message: TaskiqMessage) -> None:
        logger.info("<-- enqueued %s id=%s", message.task_name, message.task_id)

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        self._tokens[message.task_id] = request_id_ctx.set(message.task_id)
        self._starts[message.task_id] = time.perf_counter()
        logger.info("--> exec %s id=%s", message.task_name, message.task_id)
        return message

    def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        elapsed_ms = self._elapsed_ms(message.task_id)
        logger.info(
            "<-- exec %s id=%s %s %.2fms",
            message.task_name,
            message.task_id,
            "err" if result.is_err else "ok",
            elapsed_ms,
        )
        self._reset(message.task_id)

    def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult,
        exception: BaseException,
    ) -> None:
        elapsed_ms = self._elapsed_ms(message.task_id)
        logger.exception(
            "<-- exec %s id=%s failed after %.2fms: %s",
            message.task_name,
            message.task_id,
            elapsed_ms,
            exception,
        )
        self._reset(message.task_id)

    def _elapsed_ms(self, task_id: str) -> float:
        start = self._starts.pop(task_id, None)
        if start is None:
            return 0.0
        return (time.perf_counter() - start) * 1000

    def _reset(self, task_id: str) -> None:
        token = self._tokens.pop(task_id, None)
        if token is not None:
            request_id_ctx.reset(token)  # type: ignore[arg-type]
