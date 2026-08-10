from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from math import ceil

from throttled.asyncio import RateLimiterType, Throttled
from throttled.asyncio.store import RedisStore
from throttled.exceptions import BaseThrottledError
from throttled.rate_limiter import per_duration

from src.common.errors.exceptions import TooManyRequestsException
from src.core import resources
from src.core.config import RateLimitRule, Settings, get_settings
from src.core.logger import logger


class RateLimitVerdict:
    """What one `hit` decided, plus the numbers a client needs to back off."""

    __slots__ = ("allowed", "limit", "remaining", "reset_after", "retry_after")

    def __init__(
        self,
        allowed: bool,
        limit: int,
        remaining: int,
        reset_after: int,
        retry_after: int,
    ) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.reset_after = reset_after
        self.retry_after = retry_after

    def headers(self) -> dict[str, str]:
        """The `RateLimit-*` headers for this verdict (RFC-style names)."""
        return {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset_after),
        }


class RateLimiter:
    """A sliding-window limiter over Redis, shared by every rule.

    The counters live in Redis rather than in the process, so N workers enforce
    one budget instead of N. Throttles are cached per ``limit/window`` shape:
    the rules are read from config, so the set is small and fixed at boot.

    Deliberately not a DI-provided dependency — the middleware runs outside the
    request scope and a `Depends` guard has no container, so both reach it
    through `get_limiter()`.
    """

    def __init__(self, settings: Settings) -> None:
        self.cfg = settings.rate_limit
        self.store = RedisStore(server=settings.redis.url)
        self._throttles: dict[str, Throttled] = {}

    def _throttle(self, rule: RateLimitRule) -> Throttled:
        name = f"{rule.limit}/{rule.window_seconds}"
        throttle = self._throttles.get(name)
        if throttle is None:
            throttle = Throttled(
                using=RateLimiterType.SLIDING_WINDOW.value,
                quota=per_duration(timedelta(seconds=rule.window_seconds), limit=rule.limit),
                store=self.store,
            )
            self._throttles[name] = throttle
        return throttle

    async def hit(
        self,
        key: str,
        rule: RateLimitRule,
        *,
        closed_when_down: bool = False,
    ) -> RateLimitVerdict:
        """Spend one call from `key`'s budget and report what is left.

        When the store is unreachable the limiter has no counters to judge by,
        and the choice is which way to fail. It fails **open** by default —
        losing Redis should not take the API down with it — but a caller that
        guards something expensive to brute-force (a login) passes
        ``closed_when_down=True`` and gets a refusal instead.

        Args:
            key (str): The bucket to charge (namespace + rule + caller).
            rule (RateLimitRule): The budget to charge it against.
            closed_when_down (bool): Refuse, rather than allow, when the store
                is unreachable.
        Returns:
            (RateLimitVerdict): The decision and its headers.
        """
        try:
            result = await self._throttle(rule).limit(key)
        except BaseThrottledError as exc:
            logger.warning("rate limit store is unreachable for %s: %s", key, exc)
            return RateLimitVerdict(
                allowed=not closed_when_down,
                limit=rule.limit,
                remaining=0,
                reset_after=rule.window_seconds,
                retry_after=rule.window_seconds,
            )
        state = result.state
        return RateLimitVerdict(
            allowed=not result.limited,
            limit=state.limit,
            remaining=state.remaining,
            reset_after=ceil(state.reset_after),
            retry_after=ceil(state.retry_after),
        )

    def refuse(self, verdict: RateLimitVerdict) -> TooManyRequestsException:
        """Turn a spent budget into the exception to raise (or serialise)."""
        return TooManyRequestsException(
            message="too many requests, try again later",
            message_code=resources.TOO_MANY_REQUESTS,
            limit=verdict.limit,
            remaining=verdict.remaining,
            retry_after=verdict.retry_after,
        )


@lru_cache
def get_limiter() -> RateLimiter:
    return RateLimiter(get_settings())
