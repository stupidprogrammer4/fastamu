import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, cast

from dishka import AsyncContainer, FromDishka
from dishka.integrations.taskiq import inject
from pydantic import Field, TypeAdapter
from taskiq import AsyncBroker, AsyncTaskiqDecoratedTask

from fastamu.messaging.projections.contracts.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    Projection,
)
from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
    AbstractUnProjection,
)
from fastamu.messaging.projections.contracts.patch import (
    AbstractBatchPatchProjection,
    AbstractPatchProjection,
)
from fastamu.messaging.projections.contracts.results import (
    BulkItemResult,
    ProjectionBatchError,
)
from fastamu.tasks.projection.delivery.labels import RETRY_DELAY

type ProjectionResult = None | list[BulkItemResult]
type ProjectionTask = AsyncTaskiqDecoratedTask[..., ProjectionResult]


class Register:
    _queue_name = TypeAdapter(Annotated[str, Field(strict=True, min_length=1)])

    def __init__(self) -> None:
        self.tasks: dict[type[Projection], ProjectionTask] = {}

    def register(
        self, projection: type[Projection], broker: AsyncBroker
    ) -> ProjectionTask:
        task = self.tasks.get(projection)
        if task is None:
            task = self._register_projection(projection, broker)
            self.tasks[projection] = task
        elif task.broker is not broker:
            raise ValueError("Projection is registered on another broker")
        return task

    def get(self, projection: type[Projection]) -> ProjectionTask:
        return self.tasks[projection]

    def _result(self, result: ProjectionResult) -> ProjectionResult:
        if result is not None and any(not item.settled for item in result):
            raise ProjectionBatchError(result)
        return result

    def _register_projection(
        self, projection: type[Projection], broker: AsyncBroker
    ) -> ProjectionTask:
        if inspect.isabstract(projection):
            raise TypeError("Cannot register an abstract projection")

        queue_name = self._queue_name.validate_python(
            getattr(projection, "queue_name", None)
        )
        task_name = f"{projection.__module__}:{projection.__qualname__}"
        if broker.find_task(task_name) is not None:
            raise ValueError(f"Task name is already registered: {task_name}")

        if issubclass(projection, AbstractBatchProjection):
            execute = self._batch(projection, projection.batch_project)
        elif issubclass(projection, AbstractBatchPatchProjection):
            execute = self._batch(projection, projection.batch_project)
        elif issubclass(projection, AbstractBatchUnProjection):
            execute = self._batch(projection, projection.batch_unproject)
        elif issubclass(projection, AbstractProjection):
            execute = self._single(projection, projection.project)
        elif issubclass(projection, AbstractPatchProjection):
            execute = self._single(projection, projection.project)
        elif issubclass(projection, AbstractFanoutProjection):
            execute = self._single(projection, projection.project)
        elif issubclass(projection, AbstractUnProjection):
            execute = self._single(projection, projection.unproject)
        else:
            raise TypeError("Unsupported projection class")

        labels: dict[str, str | bool | int | float] = {
            "queue_name": queue_name,
            "retry_on_error": projection.retry_policy is not None,
        }
        if projection.retry_policy is not None:
            labels.update(
                max_retries=projection.retry_policy.max_attempts,
                **{RETRY_DELAY: projection.retry_policy.delay},
            )
        task = cast(
            ProjectionTask,
            broker.task(task_name=task_name, **labels)(execute),
        )
        return task

    def _single[P: Projection](
        self,
        projection: type[P],
        operation: Callable[[P, int], Awaitable[ProjectionResult]],
    ) -> Callable[..., Awaitable[ProjectionResult]]:
        @inject(patch_module=True)
        async def task(
            id: int, container: FromDishka[AsyncContainer]
        ) -> ProjectionResult:
            instance = await container.get(projection)
            return self._result(await operation(instance, id))

        return task

    def _batch[P: Projection](
        self,
        projection: type[P],
        operation: Callable[[P, Sequence[int]], Awaitable[ProjectionResult]],
    ) -> Callable[..., Awaitable[ProjectionResult]]:
        @inject(patch_module=True)
        async def task(
            ids: list[int], container: FromDishka[AsyncContainer]
        ) -> ProjectionResult:
            instance = await container.get(projection)
            return self._result(await operation(instance, ids))

        return task


register = Register()
