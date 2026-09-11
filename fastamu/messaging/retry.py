"""Opt-in retry budgets for handlers that are safe to execute again."""

import random
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class RetryDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    delay: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_delay: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=5, ge=1)
    delays: tuple[Annotated[float, Field(gt=0, allow_inf_nan=False)], ...] = (
        5,
        30,
        120,
        600,
    )
    jitter: float = Field(default=0.1, ge=0, le=1, allow_inf_nan=False)
    retry_on: tuple[type[Exception], ...] = (Exception,)
    stop_on: tuple[type[Exception], ...] = ()

    def retryable(self, error: Exception) -> bool:
        return isinstance(error, self.retry_on) and not isinstance(
            error, self.stop_on
        )

    def delay(self, attempt: int) -> float:
        base = self.delays[min(attempt, len(self.delays)) - 1]
        return base * (1 + random.random() * self.jitter)

    def decide(self, error: Exception, attempt: int) -> RetryDecision:
        """Return no delay to park; override this method for custom policy."""
        if (
            attempt >= self.max_attempts
            or not self.delays
            or not self.retryable(error)
        ):
            return RetryDecision()
        base = self.delays[min(attempt, len(self.delays)) - 1]
        return RetryDecision(
            delay=self.delay(attempt), max_delay=base * (1 + self.jitter)
        )
