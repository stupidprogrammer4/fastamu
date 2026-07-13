from abc import ABC, abstractmethod
from typing import Generic, Sequence, TypeVar

from src.infra.es.repository import TESRepository
from src.infra.postgres.repository.typing import TPGRepository


class AbstractESProjection(ABC, Generic[TPGRepository, TESRepository]):
    """Builds an Elasticsearch read-model from the Postgres source of truth
    (the CQRS read side).

    Subclass per read-model, wiring the PG repository (read side) and the ES
    repository (write side), and implement `project` to (re)index a single
    entity by id. Dispatched in the background by the `@project` decorator.
    """

    def __init__(self, pg_repo: TPGRepository, es_repo: TESRepository) -> None:
        self.pg_repo = pg_repo
        self.es_repo = es_repo

    @abstractmethod
    async def project(self, id: int) -> bool:
        """(Re)build the ES document for the entity with this ``id``."""
        ...

    async def unproject(self, id: int) -> bool:
        """Remove the entity's ES document (called after a delete).

        Args:
            id (int): ID of the entity whose document to drop.
        Returns:
            (bool): True once the document is gone from the index.
        """
        existing = await self.es_repo.get(str(id))
        if existing is not None:
            await self.es_repo.delete(existing)
        return True


TESProjection = TypeVar("TESProjection", bound=AbstractESProjection)


class AbstractBatchProjection(ABC, Generic[TPGRepository, TESRepository]):
    """The batch counterpart of `AbstractESProjection`: (re)index MANY entities
    in one background job — one bulk read + one bulk index, no per-id loop.

    Dispatched with the list of ids by the `@batch_project` decorator (e.g.
    after a bulk write like a platform-wide deactivation).
    """

    def __init__(self, pg_repo: TPGRepository, es_repo: TESRepository) -> None:
        self.pg_repo = pg_repo
        self.es_repo = es_repo

    @abstractmethod
    async def batch_project(self, ids: Sequence[int]) -> bool:
        """(Re)build the ES documents for the entities with these ``ids``."""
        ...


TBatchProjection = TypeVar("TBatchProjection", bound=AbstractBatchProjection)
