from unittest.mock import AsyncMock, patch

import pytest
from dishka import make_async_container

from papilio.core.config import get_settings
from papilio.errors.exceptions import TooManyRequestsException
from papilio.infra.redis.client import RedisClient
from papilio.providers.base import CoreProvider
from papilio.providers.rate_limit.redis import RedisRateProvider
from papilio.providers.redis import RedisProvider
from papilio.tools.rate_limit.base import Unavailable
from papilio.tools.rate_limit.config import RateLimitRule
from papilio.tools.rate_limit.limiter import RateLimiter


@pytest.mark.asyncio
async def test_limits_use_shared_client_without_creating_another_pool():
    container = make_async_container(
        CoreProvider(),
        RedisProvider(get_settings().redis),
        RedisRateProvider(),
    )
    try:
        redis = await container.get(RedisClient)
        script = AsyncMock(side_effect=[(0, 1, "0"), (1, 1, "10")])
        with (
            patch.object(redis.client, "register_script", return_value=script),
            patch(
                "throttled.store.redis_pool.ConnectionFactory.connect",
                side_effect=AssertionError(
                    "Rate limiting opened another client"
                ),
            ),
        ):
            limiter = await container.get(RateLimiter)
            assert await container.get(RateLimiter) is limiter
            assert limiter.backend.store._backend.get_client() is redis.client
            rule = RateLimitRule(limit=1, window_seconds=60)
            assert await limiter.check("test:shared", rule) is not None
            with pytest.raises(TooManyRequestsException):
                await limiter.check("test:shared", rule)
            assert script.await_count == 2
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_container_alone_closes_shared_client():
    container = make_async_container(
        CoreProvider(),
        RedisProvider(get_settings().redis),
        RedisRateProvider(),
    )
    redis = await container.get(RedisClient)
    await container.get(RateLimiter)
    with patch.object(redis.client, "aclose", new_callable=AsyncMock) as close:
        await container.close()
        close.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_outage_respects_failure_policy():
    backend = AsyncMock()
    backend.limit.side_effect = Unavailable("offline")
    limiter = RateLimiter(backend)
    rule = RateLimitRule(limit=1, window_seconds=60)
    assert await limiter.check("test:outage", rule) is None
    with pytest.raises(TooManyRequestsException):
        await limiter.check("test:outage", rule, closed_when_down=True)
    backend.limit.side_effect = ValueError("programming error")
    with pytest.raises(ValueError):
        await limiter.check("test:outage", rule)


async def test_native_redis_outage_reaches_the_shared_failure_policy():
    from redis.asyncio import Redis
    from redis.exceptions import ConnectionError

    from papilio.tools.rate_limit.backends.redis import RedisBackend

    client = Redis()
    script = AsyncMock(side_effect=ConnectionError("offline"))
    try:
        with patch.object(client, "register_script", return_value=script):
            limiter = RateLimiter(RedisBackend(client))
            rule = RateLimitRule(limit=1, window_seconds=60)
            assert await limiter.check("test:offline", rule) is None
            with pytest.raises(TooManyRequestsException):
                await limiter.check(
                    "test:offline", rule, closed_when_down=True
                )
    finally:
        await client.aclose()
