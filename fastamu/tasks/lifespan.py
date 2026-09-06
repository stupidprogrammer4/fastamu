"""Only enabled task backends participate in application startup."""

from contextlib import AsyncExitStack, asynccontextmanager

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import get_settings


@asynccontextmanager
async def task_lifespan():
    config = get_settings().tasks
    bootstrapper = get_bootstrapper()
    async with AsyncExitStack() as stack:
        if config.projection is not None:
            from fastamu.tasks.projection.broker import broker
            from fastamu.tasks.projection.registry import registry

            bootstrapper.boot_projections()
            registry.build()
            if registry.queues:
                stack.push_async_callback(broker.shutdown)
                await broker.startup()
        if config.schedulers is not None:
            from fastamu.tasks.schedulers.broker import broker

            stack.push_async_callback(broker.shutdown)
            await broker.startup()
        if config.events is not None:
            from fastamu.tasks.events.broker import broker

            routers = [
                *bootstrapper.boot_subscribers(),
                *bootstrapper.boot_publishers(),
            ]
            for router in {id(r): r for r in routers}.values():
                broker.include_router(router)
            stack.push_async_callback(broker.stop)
            await broker.connect()
        yield
