from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from fastamu.messaging.projections.contracts.policies import RetryPolicy
from fastamu.messaging.projections.contracts.results import BulkItemResult


class AbstractUnProjection(ABC):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def unproject(self, id: int) -> None:
        await self._es_query(id)

    @abstractmethod
    async def _es_query(self, id: int) -> None: ...


class AbstractBatchUnProjection(ABC):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def batch_unproject(
        self, ids: Sequence[int]
    ) -> list[BulkItemResult]:
        results: list[BulkItemResult] = []
        if ids:
            results = await self._es_query(ids)
        return results

    @abstractmethod
    async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]: ...
