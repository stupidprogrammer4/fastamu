from collections.abc import Sequence
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict


class FailureRecord(BaseModel):
    """One projection input that has not been reflected yet."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    input_id: int
    error: str
    failed_at: float
    attempts: int = 0

    def attempted(self) -> Self:
        return self.model_copy(update={"attempts": self.attempts + 1})


class FailureStore(Protocol):
    """A queue of unreflected inputs, per projection.

    Taking removes; whatever is not settled is handed back.
    """

    async def record(
        self,
        projection_name: str,
        ids: Sequence[int],
        error: str,
    ) -> None: ...

    async def take(
        self,
        projection_name: str,
        limit: int,
    ) -> list[FailureRecord]: ...

    async def requeue(
        self,
        projection_name: str,
        records: Sequence[FailureRecord],
    ) -> None: ...
