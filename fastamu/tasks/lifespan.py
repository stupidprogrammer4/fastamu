"""Only enabled task backends participate in application startup."""

from contextlib import AsyncExitStack, asynccontextmanager

from dishka import AsyncContainer

from fastamu.core.config import get_settings


@asynccontextmanager
async def task_lifespan(container: AsyncContainer | None = None):
    """Start the brokers an application publishes through.

    Pass the application container to give publication failures somewhere to
    go: with repair configured, unpublished IDs are queued for it instead of
    surfacing as an error on a write that already committed.
    """
    config = get_settings().tasks
    async with AsyncExitStack() as stack:
        if config.projection is not None:
            from fastamu.tasks.projection.broker import (
                broker as projection_broker,
            )

            stack.push_async_callback(projection_broker.shutdown)
            await projection_broker.startup()
            repair = config.projection.repair
            if repair is not None and container is not None:
                from fastamu.tasks.projection.delivery.fallback import fallback
                from fastamu.tasks.projection.repair.store import failure_queue

                fallback.use(
                    await failure_queue(container, repair), repair.targets
                )
                stack.callback(fallback.clear)
        if config.schedulers is not None:
            from fastamu.tasks.schedulers.broker import broker

            stack.push_async_callback(broker.shutdown)
            await broker.startup()
        yield
