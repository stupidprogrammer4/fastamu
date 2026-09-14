from dishka import Scope, provide

from papilio.infra.redis.client import RedisClient
from papilio.tools.rate_limit.backends.redis import RedisBackend
from papilio.tools.rate_limit.base import Backend

from .base import RateLimitProvider


class RedisRateProvider(RateLimitProvider):
    @provide(scope=Scope.APP)
    def backend(self, redis: RedisClient) -> Backend:
        return RedisBackend(redis.client)
