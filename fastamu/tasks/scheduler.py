from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisScheduleSource

from fastamu.core.config import get_settings
from fastamu.tasks.broker import broker

settings = get_settings()

redis_schedule_source = RedisScheduleSource(
    url=settings.taskiq.redis_url,
    max_connection_pool_size=settings.taskiq.max_connection_pool_size,
)

scheduler = TaskiqScheduler(
    broker=broker, sources=[LabelScheduleSource(broker), redis_schedule_source]
)
