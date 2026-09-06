from unittest.mock import AsyncMock, patch

import pytest
from dishka import make_async_container
from throttled.asyncio import Throttled
from throttled.asyncio.store import RedisStore

from fastamu.common.errors.exceptions import TooManyRequestsException
from fastamu.core.config import RateLimitRule
from fastamu.core.provider import CoreProvider
from fastamu.infra.redis.client import RedisClient
from fastamu.web.ratelimit import RateLimitProvider, _check


@pytest.mark.asyncio
async def test_limits_use_shared_client_without_creating_another_pool():
    container = make_async_container(CoreProvider(), RateLimitProvider())
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
            limiter = await container.get(Throttled)
            assert await container.get(Throttled) is limiter
            assert (
                await container.get(RedisStore)
            )._backend.get_client() is redis.client
            rule = RateLimitRule(limit=1, window_seconds=60)
            assert await _check(limiter, "test:shared", rule) is not None
            with pytest.raises(TooManyRequestsException):
                await _check(limiter, "test:shared", rule)
            assert script.await_count == 2
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_container_alone_closes_shared_client():
    container = make_async_container(CoreProvider(), RateLimitProvider())
    redis = await container.get(RedisClient)
    await container.get(Throttled)
    with patch.object(redis.client, "aclose", new_callable=AsyncMock) as close:
        await container.close()
        close.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_outage_respects_failure_policy():
    from throttled.exceptions import StoreUnavailableError

    limiter = AsyncMock(spec=Throttled)
    limiter.limit.side_effect = StoreUnavailableError("offline")
    rule = RateLimitRule(limit=1, window_seconds=60)
    assert await _check(limiter, "test:outage", rule) is None
    with pytest.raises(TooManyRequestsException):
        await _check(limiter, "test:outage", rule, closed_when_down=True)
    limiter.limit.side_effect = ValueError("programming error")
    with pytest.raises(ValueError):
        await _check(limiter, "test:outage", rule)
