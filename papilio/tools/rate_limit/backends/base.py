"""Shared implementation for the throttled-py backends."""

from collections.abc import Sequence
from datetime import timedelta
from functools import lru_cache

from throttled.asyncio.rate_limiter.sliding_window import (
    SlidingWindowRateLimiter,
)
from throttled.asyncio.store.base import BaseAtomicAction, BaseStore
from throttled.exceptions import StoreUnavailableError
from throttled.rate_limiter import per_duration

from papilio.tools.rate_limit.config import RateLimitRule

from ..base import Result, State, Unavailable


class ThrottledBackend:
    def __init__(
        self,
        store: BaseStore,
        *,
        actions: Sequence[type[BaseAtomicAction]] = (),
    ) -> None:
        self.store = store
        self._actions = actions
        self._limiter = lru_cache(maxsize=128)(self._make_limiter)

    def _make_limiter(
        self, limit: int, window: int
    ) -> SlidingWindowRateLimiter:
        return SlidingWindowRateLimiter(
            quota=per_duration(timedelta(seconds=window), limit),
            store=self.store,
            additional_atomic_actions=self._actions,
        )

    async def limit(self, key: str, rule: RateLimitRule) -> Result:
        limiter = self._limiter(rule.limit, rule.window_seconds)
        try:
            result = await limiter.limit(key)
        except StoreUnavailableError as exc:
            raise Unavailable(str(exc)) from exc
        state = result.state
        return Result(
            result.limited,
            State(
                state.limit,
                state.remaining,
                state.reset_after,
                state.retry_after,
            ),
        )
