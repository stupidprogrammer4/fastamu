from collections.abc import Sequence
from typing import Any

from pydantic import StrictInt, TypeAdapter
from taskiq import NoResultError, TaskiqMessage, TaskiqMiddleware, TaskiqResult

from fastamu.messaging.projections.contracts.results import (
    BulkItemResult,
    ProjectionBatchError,
)
from fastamu.messaging.projections.repair.records import FailureStore
from fastamu.messaging.projections.repair.settlement import unresolved_ids


class ProjectionFailureMiddleware(TaskiqMiddleware):
    """Queue the inputs a terminal projection failure left unreflected."""

    _ids = TypeAdapter(list[StrictInt])

    def __init__(
        self,
        store: FailureStore,
        projections: Sequence[str],
    ) -> None:
        super().__init__()
        self.store = store
        self.projections = set(projections)

    def _ids_of(self, message: TaskiqMessage) -> list[int]:
        """Read the IDs a projection task was called with."""
        if message.args:
            values = message.args[0]
            if not isinstance(values, (list, tuple)):
                values = [values]
        elif "ids" in message.kwargs:
            values = message.kwargs["ids"]
        else:
            values = [message.kwargs["id"]]
        return self._ids.validate_python(values)

    def _results(self, exception: BaseException) -> list[BulkItemResult]:
        results: list[BulkItemResult] = []
        if isinstance(exception, ProjectionBatchError):
            results = exception.results
        return results

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        # SmartRetry runs first and reports a scheduled retry as NoResultError.
        terminal = not isinstance(result.error, NoResultError)
        if terminal and message.task_name in self.projections:
            ids = unresolved_ids(
                self._ids_of(message), self._results(exception)
            )
            await self.store.record(message.task_name, ids, str(exception))
