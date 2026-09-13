"""Dependencies used by the HTTP layer."""

from datetime import timedelta
from typing import cast

from dishka import Provider, Scope, provide
from throttled.asyncio import Throttled
from throttled.asyncio.store import RedisStore
from throttled.rate_limiter import per_duration
from throttled.types import AsyncRedisClientP

from papilio.api.rate_limit.dependencies import NamedLimits
from papilio.core.config import RateLimitRule, Settings
from papilio.infra.redis.client import RedisClient


def _limiter(rule: RateLimitRule, store: RedisStore) -> Throttled:
    return Throttled(
        using="sliding_window",
        quota=per_duration(timedelta(seconds=rule.window_seconds), rule.limit),
        store=store,
    )


class RateLimitProvider(Provider):
    """App-scoped library objects borrowing the existing Redis client."""

    scope = Scope.APP

    @provide
    def store(self, redis: RedisClient) -> RedisStore:
        store = RedisStore()
        # throttled-py 3.x lacks client=. Isolate this compatibility bridge;
        # RedisClient remains the sole owner of the pool and its shutdown.
        store._backend._client = cast(AsyncRedisClientP, redis.client)
        return store

    @provide
    def general(self, settings: Settings, store: RedisStore) -> Throttled:
        return _limiter(settings.rate_limit.general, store)

    @provide
    def rules(self, settings: Settings, store: RedisStore) -> NamedLimits:
        return {
            name: _limiter(rule, store)
            for name, rule in settings.rate_limit.rules.items()
        }
