"""HTTP integration for throttled-py; no custom rate-limit algorithms."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from math import ceil
from typing import cast

from dishka import Provider, Scope, provide
from fastapi import Request
from fastapi.params import Depends
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response
from throttled.asyncio import Throttled
from throttled.asyncio.rate_limiter import RateLimitState
from throttled.asyncio.store import RedisStore
from throttled.exceptions import StoreUnavailableError
from throttled.rate_limiter import per_duration
from throttled.types import AsyncRedisClientP

from fastamu.common.errors.exceptions import TooManyRequestsException
from fastamu.core import resources
from fastamu.core.config import RateLimitRule, Settings
from fastamu.core.logger import logger
from fastamu.infra.redis.client import RedisClient
from fastamu.web.error_handlers import external_error_handler

KeyPart = Callable[[Request], Awaitable[str]]
type NamedLimits = dict[str, Throttled]


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


async def by_ip(request: Request) -> str:
    settings = await request.app.state.dishka_container.get(Settings)
    peer = request.client.host if request.client else "unknown"
    if peer in settings.rate_limit.trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            peer = forwarded.split(",")[0].strip()
    return f"ip:{peer}"


def by_body_field(field: str) -> KeyPart:
    async def key(request: Request) -> str:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = None
        value = body.get(field) if isinstance(body, dict) else None
        return f"{field}:{value or 'none'}"

    return key


def _headers(state: RateLimitState) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(state.limit),
        "RateLimit-Remaining": str(state.remaining),
        "RateLimit-Reset": str(ceil(state.reset_after)),
    }


async def _check(
    limiter: Throttled,
    key: str,
    rule: RateLimitRule,
    *,
    closed_when_down: bool = False,
) -> RateLimitState | None:
    try:
        result = await limiter.limit(key)
    except StoreUnavailableError:
        logger.warning("Rate limit Redis is unavailable")
        if not closed_when_down:
            return None
        raise TooManyRequestsException(
            message="rate limit temporarily unavailable",
            message_code=resources.TOO_MANY_REQUESTS,
            limit=rule.limit,
            remaining=0,
            retry_after=rule.window_seconds,
        ) from None
    if result.limited:
        raise TooManyRequestsException(
            message="too many requests, try again later",
            message_code=resources.TOO_MANY_REQUESTS,
            limit=result.state.limit,
            remaining=result.state.remaining,
            retry_after=ceil(result.state.retry_after),
        )
    return result.state


def rate_limit(
    name: str,
    parts: Sequence[KeyPart] = (by_ip,),
    *,
    closed_when_down: bool = False,
) -> Depends:
    """Charge independent buckets concurrently; reject if any is exhausted."""

    async def guard(request: Request) -> None:
        container = request.app.state.dishka_container
        settings = await container.get(Settings)
        if (
            not settings.rate_limit.enabled
            or name not in settings.rate_limit.rules
        ):
            return
        limiter = (await container.get(NamedLimits))[name]
        # Request body readers share one stream; extract keys before Redis I/O.
        keys = [await part(request) for part in parts]
        results = await asyncio.gather(
            *(
                _check(
                    limiter,
                    f"rl:rule:{name}:{key}",
                    settings.rate_limit.rules[name],
                    closed_when_down=closed_when_down,
                )
                for key in keys
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    return Depends(guard)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """One IP budget across all paths, including unmatched routes."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        container = request.app.state.dishka_container
        settings = await container.get(Settings)
        if not settings.rate_limit.enabled:
            return await call_next(request)
        limiter = await container.get(Throttled)
        # Keep the existing global counter namespace.
        key = (await by_ip(request)).removeprefix("ip:")
        try:
            state = await _check(
                limiter, f"rl:general:{key}", settings.rate_limit.general
            )
        except TooManyRequestsException as exc:
            response = await external_error_handler(request, exc)
            response.headers["RateLimit-Reset"] = str(
                settings.rate_limit.general.window_seconds
            )
            return response
        response = await call_next(request)
        if state is not None:
            for name, value in _headers(state).items():
                response.headers.setdefault(name, value)
        return response
