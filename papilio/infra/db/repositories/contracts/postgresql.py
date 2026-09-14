"""PostgreSQL repository capabilities and exact native result types."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, Values
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause

from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.repositories.contracts.base import (
    IdentifiedRepositoryContract,
    PersistenceRepositoryContract,
    ReaderContract,
    RepositoryContract,
    TimestampRepositoryContract,
)
from papilio.infra.db.uow import PostgreSQLUnitOfWork
from papilio.schemas.results import PagedType


class PostgreSQLReaderContract(ReaderContract[PostgreSQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: PostgreSQLUnitOfWork) -> None: ...


class PostgreSQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: PostgreSQLUnitOfWork) -> None: ...

    @abstractmethod
    def _upsert_stmt(
        self,
        row: Mapping[str, Any],
        *,
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert: ...

    @abstractmethod
    def _bulk_upsert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert: ...

    @abstractmethod
    async def upsert(
        self,
        data: T,
        *,
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> T: ...

    @abstractmethod
    async def bulk_upsert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Sequence[T]: ...

    @abstractmethod
    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Sequence[ColumnClause[Any]],
        name: str = "incoming",
    ) -> Values: ...

    @abstractmethod
    def _bulk_update_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        key_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
    ) -> Update: ...

    @abstractmethod
    async def bulk_update(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        key_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
    ) -> Sequence[T]: ...

    @abstractmethod
    async def get_one(self, *where: ColumnElement[bool]) -> T | None: ...

    @abstractmethod
    async def get_all(self, *where: ColumnElement[bool]) -> Sequence[T]: ...

    @abstractmethod
    def get_all_stream(
        self,
        batch_size: int = 100,
        *,
        where: Sequence[ColumnElement[bool]] = (),
    ) -> AsyncIterator[T]: ...

    @abstractmethod
    async def exists(self, *where: ColumnElement[bool]) -> bool: ...

    @abstractmethod
    async def count(self, *where: ColumnElement[bool]) -> int: ...

    @abstractmethod
    async def get_page(
        self,
        *,
        order_by: Sequence[ColumnElement[Any]],
        limit: int,
        offset: int = 0,
        where: Sequence[ColumnElement[bool]] = (),
    ) -> PagedType[T]: ...

    @abstractmethod
    async def update(
        self, where: ColumnElement[bool], changes: Mapping[str, Any]
    ) -> Sequence[T]: ...

    @abstractmethod
    async def remove(self, where: ColumnElement[bool]) -> int: ...


class PostgreSQLIdentifiedRepositoryContract[T: IdentifiedEntity](
    PostgreSQLRepositoryContract[T], IdentifiedRepositoryContract[T]
):
    @abstractmethod
    async def update_by_id(
        self, id: int, changes: Mapping[str, Any]
    ) -> T | None: ...

    @abstractmethod
    async def update_by_ids(
        self, ids: Sequence[int], changes: Mapping[str, Any]
    ) -> Sequence[T]: ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> T | None: ...


class PostgreSQLTimestampRepositoryContract[T: TimestampEntity](
    PostgreSQLRepositoryContract[T], TimestampRepositoryContract[T]
): ...


class PostgreSQLPersistenceRepositoryContract[T: PersistenceEntity](
    PostgreSQLIdentifiedRepositoryContract[T],
    PostgreSQLTimestampRepositoryContract[T],
    PersistenceRepositoryContract[T],
): ...
