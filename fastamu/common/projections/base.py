from abc import ABC, abstractmethod
from collections.abc import Sequence

from elasticsearch.dsl import AsyncDocument

from fastamu.common.models.base import Base
from fastamu.common.projections.convertor import Convertor
from fastamu.common.projections.definition import ProjectionDefinition


class AbstractProjection[TModel: Base, TDocument: AsyncDocument](
    ProjectionDefinition, ABC
):
    """Read one model, convert it and write one document.

    A missing source model is a no-op, not an implicit destination deletion.
    Query and conversion errors propagate to the caller.
    """

    def __init__(self, convertor: Convertor[TModel, TDocument]) -> None:
        self.convertor = convertor

    async def project(self, id: int) -> None:
        model = await self._db_query(id)
        if model is None:
            return
        document = self.convertor.convert(model)
        await self._es_query(document)

    @abstractmethod
    async def _db_query(self, id: int) -> TModel | None:
        """Load one source model and its conversion dependencies."""
        ...

    @abstractmethod
    async def _es_query(self, document: TDocument) -> None:
        """Write one destination document; raise on failure."""
        ...


class AbstractFanoutProjection[TModel, TDocument](ProjectionDefinition, ABC):
    """Read one source identity and write all documents derived from it."""

    def __init__(self, convertor: Convertor[TModel, TDocument]) -> None:
        self.convertor = convertor

    async def project(self, id: int) -> None:
        models = await self._db_query(id)
        if not models:
            return
        documents = [self.convertor.convert(model) for model in models]
        await self._es_query(documents)

    @abstractmethod
    async def _db_query(self, id: int) -> Sequence[TModel]:
        """Load every source model represented by one source identity."""
        ...

    @abstractmethod
    async def _es_query(self, documents: Sequence[TDocument]) -> None:
        """Write the derived documents together; raise on failure."""
        ...


class AbstractBatchProjection[TModel, TDocument](ProjectionDefinition, ABC):
    """Coordinate bulk reads, pure conversion and bulk destination writes.

    Subclasses implement only the two query hooks and may inject repositories
    in their constructors. Missing source models produce no document; deletion
    of stale destination documents is not implicit. Errors propagate.
    """

    def __init__(self, convertor: Convertor[TModel, TDocument]) -> None:
        self.convertor = convertor

    async def batch_project(self, ids: Sequence[int]) -> None:
        """Read once, convert in memory, then write once for the batch."""
        if not ids:
            return
        models = await self._db_query(list(dict.fromkeys(ids)))
        if not models:
            return
        documents = [self.convertor.convert(model) for model in models]
        await self._es_query(documents)

    @abstractmethod
    async def _db_query(self, ids: Sequence[int]) -> Sequence[TModel]:
        """Load source models and conversion dependencies in bulk."""
        ...

    @abstractmethod
    async def _es_query(self, documents: Sequence[TDocument]) -> None:
        """Write documents in bulk; raise if any destination write fails."""
        ...


class AbstractUnProjection(ProjectionDefinition, ABC):
    """Remove a document by ID without loading a deleted source model."""

    async def unproject(self, id: int) -> None:
        await self._es_query(id)

    @abstractmethod
    async def _es_query(self, id: int) -> None:
        """Delete the destination document; an absent document is a no-op."""
        ...
