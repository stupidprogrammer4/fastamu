from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Protocol

from elasticsearch.dsl import AsyncDocument
from pydantic import BaseModel

from fastamu.messaging.projections.contracts.policies import RetryPolicy
from fastamu.messaging.projections.contracts.results import BulkItemResult


class Projection(Protocol):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None


class AbstractProjection[TModel: BaseModel, TDocument: AsyncDocument](ABC):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def project(self, id: int) -> None:
        model = await self._db_query(id)
        document = self._convert(model)
        await self._es_query(document)

    @abstractmethod
    async def _db_query(self, id: int) -> TModel:
        """Return the source model or raise an application-defined error."""
        ...

    @abstractmethod
    def _convert(self, model: TModel) -> TDocument: ...

    @abstractmethod
    async def _es_query(self, document: TDocument) -> None: ...


class AbstractBatchProjection[TModel: BaseModel, TDocument: AsyncDocument](
    ABC
):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def batch_project(self, ids: Sequence[int]) -> list[BulkItemResult]:
        results: list[BulkItemResult] = []
        if ids:
            documents = [
                self._convert(model) for model in await self._db_query(ids)
            ]
            if documents:
                results = await self._es_query(documents)
        return results

    @abstractmethod
    async def _db_query(self, ids: Sequence[int]) -> Sequence[TModel]: ...

    @abstractmethod
    def _convert(self, model: TModel) -> TDocument: ...

    @abstractmethod
    async def _es_query(
        self, documents: Sequence[TDocument]
    ) -> list[BulkItemResult]: ...


class AbstractFanoutProjection[TModel: BaseModel, TDocument: AsyncDocument](
    ABC
):
    queue_name: ClassVar[str]
    retry_policy: ClassVar[RetryPolicy | None] = None

    async def project(self, id: int) -> list[BulkItemResult]:
        results: list[BulkItemResult] = []
        documents = [
            self._convert(model) for model in await self._db_query(id)
        ]
        if documents:
            results = await self._es_query(documents)
        return results

    @abstractmethod
    async def _db_query(self, id: int) -> Sequence[TModel]: ...

    @abstractmethod
    def _convert(self, model: TModel) -> TDocument: ...

    @abstractmethod
    async def _es_query(
        self, documents: Sequence[TDocument]
    ) -> list[BulkItemResult]: ...
