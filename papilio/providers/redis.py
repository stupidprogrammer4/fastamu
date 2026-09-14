from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from papilio.core.config import RedisConfig
from papilio.infra.redis.client import RedisClient


class RedisProvider(Provider):
    def __init__(self, config: RedisConfig) -> None:
        super().__init__()
        self.config = config

    @provide(scope=Scope.APP)
    async def redis(self) -> AsyncIterator[RedisClient]:
        client = RedisClient(
            self.config.url,
            max_connections=self.config.max_connections,
            socket_timeout=self.config.socket_timeout,
            socket_connect_timeout=self.config.socket_connect_timeout,
            health_check_interval=self.config.health_check_interval,
        )
        try:
            yield client
        finally:
            await client.close()
