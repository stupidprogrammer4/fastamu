from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import Depends, Request

from src.core.config import RateLimitRule, Settings, get_settings
from src.infra.ratelimit.keys import client_ip
from src.infra.ratelimit.limiter import limiter_for

NAMESPACE = "rl:rule"

KeyPart = Callable[[Request], Awaitable[str]]


async def by_ip(request: Request) -> str:
    return f"ip:{client_ip(request)}"


def by_body_field(field: str) -> KeyPart:
    """Count a caller by one field of the JSON body — a username, a mobile
    number, whatever the endpoint is really being hammered for.

    A body that is not a JSON object, or is missing the field, still yields a
    bucket (`none`): a malformed request must be counted somewhere, or it is
    the one shape that gets in for free.

    Args:
        field (str): The key to read out of the body.
    Returns:
        (KeyPart): A part to hand to `rate_limit`.
    """

    async def part(request: Request) -> str:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return f"{field}:none"
        value = body.get(field) if isinstance(body, dict) else None
        return f"{field}:{value or 'none'}"

    return part


async def _settings_of(request: Request) -> Settings:
    """The settings this request is being served under.

    Read from the request's own container when there is one, so a test app
    built on other settings is limited by *its* budgets rather than the ones
    in the working directory's config.yml.
    """
    container = getattr(request.state, "dishka_container", None)
    if container is None:
        return get_settings()
    settings = await container.get(Settings)
    return settings


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
        settings = await _settings_of(request)
        cfg = settings.rate_limit
        if not cfg.enabled:
            return
        rule: RateLimitRule | None = cfg.rules.get(name)
        if rule is None:
            return
        limiter = limiter_for(settings)
        for part in parts:
            key = f"{NAMESPACE}:{name}:{await part(request)}"
            verdict = await limiter.hit(
                key, rule, closed_when_down=closed_when_down
            )
            if not verdict.allowed:
                raise limiter.refuse(verdict)

    return Depends(guard)
