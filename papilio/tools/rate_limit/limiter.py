"""Reusable rate limiting and outage policy, independent of HTTP."""

from math import ceil

from papilio.core import resources
from papilio.core.logger import logger
from papilio.errors.exceptions import TooManyRequestsException
from papilio.tools.rate_limit.config import RateLimitRule

from .base import Backend, State, Unavailable


class RateLimiter:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    async def check(
        self,
        key: str,
        rule: RateLimitRule,
        *,
        closed_when_down: bool = False,
    ) -> State | None:
        try:
            result = await self.backend.limit(key, rule)
        except Unavailable:
            logger.warning("Rate limit backend is unavailable")
            if closed_when_down:
                raise TooManyRequestsException(
                    message="rate limit temporarily unavailable",
                    message_code=resources.TOO_MANY_REQUESTS,
                    limit=rule.limit,
                    remaining=0,
                    retry_after=rule.window_seconds,
                ) from None
            return None
        if result.limited:
            raise TooManyRequestsException(
                message="too many requests, try again later",
                message_code=resources.TOO_MANY_REQUESTS,
                limit=result.state.limit,
                remaining=result.state.remaining,
                retry_after=ceil(result.state.retry_after),
            )
        return result.state
