from dishka import AsyncContainer

from fastamu.core.config import ProjectionRepairConfig
from fastamu.infra.redis.client import RedisClient
from fastamu.messaging.projections.repair.queue import RedisFailureQueue


async def failure_queue(
    container: AsyncContainer,
    config: ProjectionRepairConfig,
) -> RedisFailureQueue:
    """Build the configured queue on the Redis client already in use."""
    return RedisFailureQueue(
        await container.get(RedisClient),
        config.prefix,
        config.max_attempts,
        config.max_pending,
    )
