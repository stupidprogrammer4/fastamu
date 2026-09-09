"""Class discovery is synchronous; brokers and tasks are built at startup."""

import inspect
from collections.abc import Awaitable, Callable

from dishka import AsyncContainer
from dishka.integrations.taskiq import FromDishka, inject
from taskiq import TaskiqMessage

from fastamu.common.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.core.config import get_settings
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.infra.db.versions import ProjectionTicket


async def _prepare_execution(
    message: TaskiqMessage,
    container: AsyncContainer,
    projection: type,
    ids: list[int],
) -> ProjectionTicket | None:
    value = message.labels.get("projection_version")
    if value is None:
        if "projection_transaction_id" in message.labels:
            raise ValueError(
                "Legacy transaction message requires reconciliation"
            )
        return None
    ticket = ProjectionTicket.model_validate_json(value)
    name = f"{projection.__module__}.{projection.__qualname__}"
    if (
        ticket.projection != name
        or [row.target_id for row in ticket.entries] != ids
    ):
        raise ValueError("Projection version does not match the task payload")
    await container.get(DBUnitOfWork)
    return await DBUnitOfWork.pending_projection(ticket)


class ProjectionRegistry:
    def __init__(self):
        self.definitions: dict[str, type] = {}
        self.queues: dict = {}
        self.tasks: dict = {}

    def add(self, projection: type) -> None:
        if not projection.queue_name or not projection.queue_name.strip():
            raise ValueError("Projection queue_name must not be empty")
        name = f"{projection.__module__}.{projection.__qualname__}"
        existing = self.definitions.get(name)
        if existing is not None and existing is not projection:
            raise ValueError(f"Duplicate projection task: {name}")
        self.definitions[name] = projection

    def build(self, broker) -> None:
        from taskiq_aio_pika import Queue

        config = get_settings().tasks.projection
        if config is None:
            raise RuntimeError("CQRS is disabled; configure tasks.projection")
        for name, projection in self.definitions.items():
            if name in self.tasks or inspect.isabstract(projection):
                continue
            queue = projection.queue_name
            if queue not in self.queues:
                self.queues[queue] = Queue(
                    name=queue,
                    routing_key=queue,
                    arguments={"x-single-active-consumer": True},
                )
                broker.with_queue(self.queues[queue])
            handler = self._handler(projection)
            # Bind the concrete Dishka dependency once at registration.
            handler.__annotations__["instance"] = FromDishka[projection]
            self.tasks[name] = broker.task(task_name=name, queue_name=queue)(
                inject(handler, patch_module=True)
            )

    @staticmethod
    def _handler(projection) -> Callable[..., Awaitable[None]]:
        if issubclass(projection, AbstractBatchProjection):

            async def batch(
                ids: list[int],
                instance: AbstractBatchProjection,
                message: FromDishka[TaskiqMessage],
                container: FromDishka[AsyncContainer],
            ):
                ticket = await _prepare_execution(
                    message, container, projection, ids
                )
                await instance.batch_project(
                    [entry.target_id for entry in ticket.entries]
                    if ticket
                    else ids
                )
                if ticket is not None:
                    await DBUnitOfWork.complete_projection(ticket)

            return batch
        if issubclass(projection, AbstractUnProjection):

            async def remove(
                id: int,
                instance: AbstractUnProjection,
                message: FromDishka[TaskiqMessage],
                container: FromDishka[AsyncContainer],
            ):
                ticket = await _prepare_execution(
                    message, container, projection, [id]
                )
                await instance.unproject(id)
                if ticket is not None:
                    await DBUnitOfWork.complete_projection(ticket)

            return remove
        if issubclass(projection, AbstractFanoutProjection):

            async def fanout(
                id: int,
                instance: AbstractFanoutProjection,
                message: FromDishka[TaskiqMessage],
                container: FromDishka[AsyncContainer],
            ):
                ticket = await _prepare_execution(
                    message, container, projection, [id]
                )
                await instance.project(id)
                if ticket is not None:
                    await DBUnitOfWork.complete_projection(ticket)

            return fanout
        if issubclass(projection, AbstractProjection):

            async def single(
                id: int,
                instance: AbstractProjection,
                message: FromDishka[TaskiqMessage],
                container: FromDishka[AsyncContainer],
            ):
                ticket = await _prepare_execution(
                    message, container, projection, [id]
                )
                await instance.project(id)
                if ticket is not None:
                    await DBUnitOfWork.complete_projection(ticket)

            return single
        raise TypeError("Unsupported projection class")

    def task(self, projection: type):
        name = f"{projection.__module__}.{projection.__qualname__}"
        try:
            return self.tasks[name]
        except KeyError:
            raise RuntimeError(
                f"Projection {name} is not registered at startup"
            ) from None


registry = ProjectionRegistry()
