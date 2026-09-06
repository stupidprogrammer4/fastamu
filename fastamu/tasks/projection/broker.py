from dishka import make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import TaskiqEvents
from taskiq_aio_pika import AioPikaBroker

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import ProjectionConfig, get_settings
from fastamu.core.provider import CoreProvider
from fastamu.tasks.projection.receiver import RaiseProjectionErrors


def create_broker(config: ProjectionConfig) -> AioPikaBroker:
    broker = AioPikaBroker(
        config.url,
        qos=config.prefetch,
    )
    # Reversed post_execute order: Dishka closes the scope before errors
    # propagate to the ordered receiver. No result backend or retry requeue.
    broker.add_middlewares(RaiseProjectionErrors())

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def setup(state):
        container = make_async_container(
            TaskiqProvider(),
            CoreProvider(),
            *get_bootstrapper().boot_providers(),
        )
        setup_dishka(container, broker)
        state.projection_container = container

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def shutdown(state):
        await state.projection_container.close()

    return broker


config = get_settings().tasks.projection
if config is None:
    raise RuntimeError("CQRS is disabled; configure tasks.projection")
broker = create_broker(config)
