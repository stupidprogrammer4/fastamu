"""Backend contract; no HTTP, Redis or rate-limit library imports."""

from dataclasses import dataclass
from typing import Protocol

from papilio.tools.rate_limit.config import RateLimitRule


@dataclass(frozen=True, slots=True)
class State:
    limit: int
    remaining: int
    reset_after: float
    retry_after: float


@dataclass(frozen=True, slots=True)
class Result:
    limited: bool
    state: State


class Unavailable(Exception):
    """The selected counter backend could not be reached."""


class Backend(Protocol):
    async def limit(self, key: str, rule: RateLimitRule) -> Result: ...
