from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisScheduleSource

from fastamu.core.config import get_settings
from fastamu.tasks.schedulers.broker import broker

config = get_settings().tasks.schedulers
if config is None:
    raise RuntimeError("Scheduler is disabled")

redis_schedule_source = RedisScheduleSource(
    url=config.url,
    max_connection_pool_size=config.max_connection_pool_size,
)

scheduler = TaskiqScheduler(
    broker=broker, sources=[LabelScheduleSource(broker), redis_schedule_source]
)
