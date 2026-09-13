"""Named rate-limit guards and request keys."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from math import ceil

from fastapi import Request
from fastapi.params import Depends
from throttled.asyncio import Throttled
from throttled.asyncio.rate_limiter import RateLimitState
from throttled.exceptions import StoreUnavailableError

from papilio.core import resources
from papilio.core.config import RateLimitRule, Settings
from papilio.core.logger import logger
from papilio.errors.exceptions import TooManyRequestsException

KeyPart = Callable[[Request], Awaitable[str]]
type NamedLimits = dict[str, Throttled]


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


async def _check(
    limiter: Throttled,
    key: str,
    rule: RateLimitRule,
    *,
    closed_when_down: bool = False,
) -> RateLimitState | None:
    state: RateLimitState | None = None
    try:
        result = await limiter.limit(key)
    except StoreUnavailableError:
        logger.warning("Rate limit Redis is unavailable")
        if closed_when_down:
            raise TooManyRequestsException(
                message="rate limit temporarily unavailable",
                message_code=resources.TOO_MANY_REQUESTS,
                limit=rule.limit,
                remaining=0,
                retry_after=rule.window_seconds,
            ) from None
    else:
        if result.limited:
            raise TooManyRequestsException(
                message="too many requests, try again later",
                message_code=resources.TOO_MANY_REQUESTS,
                limit=result.state.limit,
                remaining=result.state.remaining,
                retry_after=ceil(result.state.retry_after),
            )
        state = result.state
    return state


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
