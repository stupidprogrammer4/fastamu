from dishka import make_async_container
from taskiq import SmartRetryMiddleware
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq_redis import RedisAsyncResultBackend, RedisScheduleSource, RedisStreamBroker

from src.core.bootstrap import get_bootstrapper
from src.core.config import get_settings
from src.core.provider import CoreProvider
from src.tasks.middlewares.logging import LoggingMiddleware

settings = get_settings()
bootstrapper = get_bootstrapper()

broker = RedisStreamBroker(
    url=settings.taskiq.redis_url,
    max_connection_pool_size=settings.taskiq.max_connection_pool_size
).with_result_backend(
    RedisAsyncResultBackend(settings.taskiq.redis_url, prefix_str="taskiq_result")
)

providers = bootstrapper.boot_providers()

container = make_async_container(
    TaskiqProvider(),
    CoreProvider(),
    *providers
)

setup_dishka(container, broker)
bootstrapper.boot_tasks()

broker.additional_streams.update({
    task.labels["queue_name"]: ">"
    for task in broker.get_all_tasks().values()
    if task.labels.get("queue_name") and task.labels["queue_name"] != broker.queue_name
})

broker.with_middlewares(
    LoggingMiddleware(),
    SmartRetryMiddleware()
)