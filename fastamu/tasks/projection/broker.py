from typing import Annotated, cast

from aio_pika import ExchangeType
from dishka import AsyncContainer, make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import TaskiqDepends, TaskiqEvents, TaskiqState
from taskiq.middlewares import SmartRetryMiddleware
from taskiq.serializers import ORJSONSerializer
from taskiq_aio_pika import AioPikaBroker, Exchange, Queue
from taskiq_redis import ListRedisScheduleSource

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import get_settings
from fastamu.core.provider import CoreProvider
from fastamu.messaging.projections.repair.orchestration import Repair
from fastamu.tasks.projection.delivery.fallback import fallback
from fastamu.tasks.projection.delivery.register import register
from fastamu.tasks.projection.delivery.retry import RetryLabelsMiddleware
from fastamu.tasks.projection.repair import targets
from fastamu.tasks.projection.repair.failures import (
    ProjectionFailureMiddleware,
)
from fastamu.tasks.projection.repair.store import failure_queue

config = get_settings().tasks.projection
if config is None:
    raise RuntimeError("Projection is disabled; configure tasks.projection")
repair_config = config.repair

bootstrapper = get_bootstrapper()
projections = bootstrapper.boot_projections()
if not projections:
    raise RuntimeError("No concrete projections found in app.projections")
if config.retry is None and any(
    projection.retry_policy is not None for projection in projections
):
    raise RuntimeError("RetryPolicy requires tasks.projection.retry")

queue_names = {projection.queue_name for projection in projections}
repair_queue = f"{config.exchange}.repair"
if config.repair is not None:
    queue_names.add(repair_queue)

broker = AioPikaBroker(
    url=config.url,
    qos=config.prefetch,
    exchange=Exchange(name=config.exchange, type=ExchangeType.DIRECT),
    task_queues=[Queue(name=name) for name in sorted(queue_names)],
    dead_letter_queue=Queue(name=f"{config.exchange}.dead_letter"),
).with_serializer(ORJSONSerializer())

retry_source: ListRedisScheduleSource | None = None
if config.retry is not None:
    retry_source = ListRedisScheduleSource(
        url=config.retry.url,
        prefix=config.retry.prefix,
        max_connection_pool_size=config.retry.max_connection_pool_size,
        buffer_size=config.retry.buffer_size,
        socket_timeout=config.retry.socket_timeout,
        socket_connect_timeout=config.retry.socket_timeout,
        serializer=ORJSONSerializer(),
        skip_past_schedules=False,
    )
    broker.with_middlewares(RetryLabelsMiddleware())

for projection in projections:
    register.register(projection, broker)

repair_targets = (
    targets.resolve(register, config.repair.targets)
    if config.repair is not None
    else {}
)

if config.repair is not None:

    @broker.task(
        task_name="fastamu.projection.repair",
        queue_name=repair_queue,
        retry_on_error=False,
        schedule=[{"interval": config.repair.interval}],
    )
    async def repair_failures(
        state: Annotated[TaskiqState, TaskiqDepends()],
    ) -> int:
        return await cast(Repair, state.projection_repair).run()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    container = make_async_container(
        TaskiqProvider(), CoreProvider(), *bootstrapper.boot_providers()
    )
    state.projection_container = container
    if repair_config is not None:
        store = await failure_queue(container, repair_config)
        fallback.use(store, repair_targets)
        state.projection_repair = Repair(
            store,
            targets.runners(repair_targets, container),
            repair_config.batch_size,
            repair_config.concurrency,
        )
        broker.with_middlewares(
            ProjectionFailureMiddleware(store, list(repair_targets))
        )
    if retry_source is not None:
        broker.with_middlewares(
            SmartRetryMiddleware(
                default_retry_label=False,
                schedule_source=retry_source,
            )
        )
    setup_dishka(container, broker)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    container = cast(AsyncContainer, state.projection_container)
    await container.close()


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN, TaskiqEvents.CLIENT_SHUTDOWN)
async def close_retry_source(state: TaskiqState) -> None:
    if retry_source is not None:
        # taskiq-redis 1.2.1's list source has no pool cleanup in shutdown().
        await retry_source._connection_pool.disconnect()
