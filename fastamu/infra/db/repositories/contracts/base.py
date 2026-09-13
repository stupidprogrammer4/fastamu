"""Abstract obligations shared by every SQL repository family."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from fastamu.common.models.entities import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.uow import UnitOfWork


class ReaderContract[U: UnitOfWork](ABC):
    """Execution context for readers that own no single table or entity.

    Readers define their own joins, aggregates and report result types.
    """

    uow: U

    @abstractmethod
    def __init__(self, uow: U) -> None: ...


class RepositoryContract[T: BaseEntity](ABC):
    table: type[T]

    @abstractmethod
    async def create(self, data: T) -> T: ...

    @abstractmethod
    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]: ...

    @abstractmethod
    async def get_all(self) -> Sequence[T]: ...

    @abstractmethod
    def get_all_stream(self, batch_size: int = 100) -> AsyncIterator[T]: ...


class IdentifiedRepositoryContract[T: IdentifiedEntity](RepositoryContract[T]):
    @abstractmethod
    async def get_by_id(self, id: int) -> T | None: ...

    @abstractmethod
    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]: ...

    @abstractmethod
    async def get_paged(self, limit: int, offset: int = 0) -> PagedType[T]: ...

    @abstractmethod
    async def remove_by_id(self, id: int) -> int: ...

    @abstractmethod
    async def remove_by_ids(self, ids: Sequence[int]) -> int: ...


class TimestampRepositoryContract[T: TimestampEntity](RepositoryContract[T]):
    @abstractmethod
    def get_stream_range(
        self, start: datetime, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def get_paged_range(
        self, start: datetime, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]: ...

    @abstractmethod
    def get_stream_gt(
        self, start: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def get_paged_gt(
        self, start: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]: ...

    @abstractmethod
    def get_stream_ge(
        self, start: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def get_paged_ge(
        self, start: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]: ...

    @abstractmethod
    def get_stream_lt(
        self, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def get_paged_lt(
        self, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]: ...

    @abstractmethod
    def get_stream_le(
        self, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def get_paged_le(
        self, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]: ...


class PersistenceRepositoryContract[T: PersistenceEntity](
    IdentifiedRepositoryContract[T], TimestampRepositoryContract[T]
): ...
