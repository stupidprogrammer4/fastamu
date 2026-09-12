from dishka import make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq_redis import (
    RedisAsyncResultBackend,
    RedisStreamBroker,
)

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import get_settings
from fastamu.core.provider import CoreProvider
from fastamu.tasks.schedulers.middlewares.logging import LoggingMiddleware

settings = get_settings()
if settings.tasks.schedulers is None:
    raise RuntimeError("Scheduler is disabled; configure tasks.schedulers")
bootstrapper = get_bootstrapper()

broker = RedisStreamBroker(
    url=settings.tasks.schedulers.url,
    max_connection_pool_size=settings.tasks.schedulers.max_connection_pool_size,
).with_result_backend(
    # without an expiry every result ever produced stays in Redis, and
    # noeviction turns a full Redis into refused writes — a stalled queue
    RedisAsyncResultBackend(
        settings.tasks.schedulers.url,
        prefix_str="taskiq_result",
        result_ex_time=settings.tasks.schedulers.result_ex_time,
    )
)

providers = bootstrapper.boot_providers()

container = make_async_container(TaskiqProvider(), CoreProvider(), *providers)

setup_dishka(container, broker)
bootstrapper.boot_schedulers()

broker.additional_streams.update(
    {
        task.labels["queue_name"]: ">"
        for task in broker.get_all_tasks().values()
        if task.labels.get("queue_name")
        and task.labels["queue_name"] != broker.queue_name
    }
)

broker.with_middlewares(LoggingMiddleware())
