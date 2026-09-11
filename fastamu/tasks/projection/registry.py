"""Class discovery is synchronous; brokers and tasks are built at startup."""

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from dishka.integrations.taskiq import FromDishka, inject
from taskiq_aio_pika import Queue

from fastamu.core.config import get_settings
from fastamu.projections import definition
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)


class ProjectionRegistry:
    def __init__(self):
        self.definitions = definition.definitions
        self.queues: dict = {}
        self.tasks: dict = {}

    def build(self, broker) -> None:
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
            if projection.retry_policy is not None:
                broker.retry_policies[name] = projection.retry_policy
            # Bind the concrete Dishka dependency once at registration.
            handler.__annotations__["instance"] = FromDishka[projection]
            self.tasks[name] = broker.task(task_name=name, queue_name=queue)(
                inject(handler, patch_module=True)
            )

    @staticmethod
    def _handler(projection) -> Callable[..., Awaitable[None]]:
        if issubclass(projection, AbstractBatchProjection):

            async def batch(ids: Any, instance: AbstractBatchProjection):
                if not isinstance(ids, list) or any(
                    type(id) is not int for id in ids
                ):
                    raise TypeError("Batch projection requires integer IDs")
                await instance.batch_project(ids)

            return batch
        if issubclass(projection, AbstractUnProjection):

            async def remove(id: Any, instance: AbstractUnProjection):
                if type(id) is not int:
                    raise TypeError("Projection ID must be an integer")
                await instance.unproject(id)

            return remove
        if issubclass(
            projection, (AbstractProjection, AbstractFanoutProjection)
        ):

            async def single(id: Any, instance):
                if type(id) is not int:
                    raise TypeError("Projection ID must be an integer")
                await instance.project(id)

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
