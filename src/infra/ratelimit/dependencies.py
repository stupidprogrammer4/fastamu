from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import Depends, Request

from src.core.config import RateLimitRule, get_settings
from src.infra.ratelimit.keys import client_ip
from src.infra.ratelimit.limiter import get_limiter

NAMESPACE = "rl:rule"

KeyPart = Callable[[Request], Awaitable[str]]


async def by_ip(request: Request) -> str:
    return f"ip:{client_ip(request)}"


def rate_limit(
    name: str,
    parts: Sequence[KeyPart] = (by_ip,),
    *,
    closed_when_down: bool = False,
) -> Any:
    """Guard a route with the named rule from `config.yml`.

    Hang it on a router or a single route like any other dependency::

        router = APIRouter(prefix="/auth", dependencies=[rate_limit("login")])

    Each part yields one bucket, and **all** of them are charged: passing
    ``(by_ip, by_username)`` limits an address hammering many accounts *and* an
    account hammered from many addresses — either budget alone leaves the other
    attack unmetered.

    A name with no rule in the config is not limited, so a rule can be switched
    off by deleting it. The refusal is raised, not returned, so it leaves
    through the normal error handlers in the standard envelope.

    Args:
        name (str): The key under `rate_limit.rules`.
        parts (Sequence[KeyPart]): The bucket dimensions to charge.
        closed_when_down (bool): Refuse when the Redis store is unreachable.
    Returns:
        (Any): A `Depends` to hang on a route or router.
    """

    async def guard(request: Request) -> None:
        cfg = get_settings().rate_limit
        if not cfg.enabled:
            return
        rule: RateLimitRule | None = cfg.rules.get(name)
        if rule is None:
            return
        limiter = get_limiter()
        for part in parts:
            key = f"{NAMESPACE}:{name}:{await part(request)}"
            verdict = await limiter.hit(
                key, rule, closed_when_down=closed_when_down
            )
            if not verdict.allowed:
                raise limiter.refuse(verdict)

    return Depends(guard)
