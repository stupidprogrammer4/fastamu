from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import ClassVar

from pydantic import BaseModel

from fastamu.messaging.projections.contracts.policies import RetryPolicy
from fastamu.messaging.projections.contracts.results import BulkItemResult


class AbstractPatchProjection[TModel: BaseModel, TPatch: BaseModel](ABC):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def project(self, id: int) -> None:
        model = await self._db_query(id)
        patch = self._convert(model)
        await self._es_query(id, patch)

    @abstractmethod
    async def _db_query(self, id: int) -> TModel: ...

    @abstractmethod
    def _convert(self, model: TModel) -> TPatch: ...

    @abstractmethod
    async def _es_query(self, id: int, patch: TPatch) -> None:
        """Write supplied fields; serialize with exclude_unset=True."""
        ...


class AbstractBatchPatchProjection[TModel: BaseModel, TPatch: BaseModel](ABC):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def batch_project(self, ids: Sequence[int]) -> list[BulkItemResult]:
        results: list[BulkItemResult] = []
        if ids:
            models = await self._db_query(ids)
            patches = {
                id: self._convert(model) for id, model in models.items()
            }
            if patches:
                results = await self._es_query(patches)
        return results

    @abstractmethod
    async def _db_query(self, ids: Sequence[int]) -> Mapping[int, TModel]:
        """Associate each source model with its patch target ID."""
        ...

    @abstractmethod
    def _convert(self, model: TModel) -> TPatch: ...

    @abstractmethod
    async def _es_query(
        self, patches: Mapping[int, TPatch]
    ) -> list[BulkItemResult]: ...
