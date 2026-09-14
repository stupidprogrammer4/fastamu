"""Named rate-limit guards and request keys."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from fastapi import Request
from fastapi.params import Depends

from papilio.core.config import Settings
from papilio.tools.rate_limit.limiter import RateLimiter

KeyPart = Callable[[Request], Awaitable[str]]


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
        limiter = await container.get(RateLimiter)
        # Request body readers share one stream; extract keys before counting.
        keys = [await part(request) for part in parts]
        results = await asyncio.gather(
            *(
                limiter.check(
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
