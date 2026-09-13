"""MySQL repository capabilities and exact native result types."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Subquery

from fastamu.common.models.entities import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from fastamu.infra.db.repositories.contracts.base import (
    IdentifiedRepositoryContract,
    PersistenceRepositoryContract,
    ReaderContract,
    RepositoryContract,
    TimestampRepositoryContract,
)
from fastamu.infra.db.uow import MySQLUnitOfWork


class MySQLReaderContract(ReaderContract[MySQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MySQLUnitOfWork) -> None: ...


class MySQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MySQLUnitOfWork) -> None: ...

    @abstractmethod
    def _bulk_insert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
    ) -> Insert: ...

    @abstractmethod
    async def bulk_insert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
    ) -> int: ...

    @abstractmethod
    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Mapping[str, ColumnClause[Any]],
        name: str = "incoming",
    ) -> Subquery: ...

    @abstractmethod
    def _upsert_stmt(
        self,
        row: Mapping[str, Any],
        *,
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert: ...

    @abstractmethod
    def _bulk_upsert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert: ...

    @abstractmethod
    async def upsert(
        self,
        data: T,
        *,
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> int: ...

    @abstractmethod
    async def bulk_upsert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> int: ...


class MySQLIdentifiedRepositoryContract[T: IdentifiedEntity](
    MySQLRepositoryContract[T], IdentifiedRepositoryContract[T]
):
    @abstractmethod
    async def update_by_id(
        self, id: int, changes: Mapping[str, Any]
    ) -> int: ...

    @abstractmethod
    async def update_by_ids(
        self, ids: Sequence[int], changes: Mapping[str, Any]
    ) -> int: ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> int: ...

    @abstractmethod
    async def bulk_update(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> int: ...

    @abstractmethod
    def _bulk_update_stmt(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> Update: ...


class MySQLTimestampRepositoryContract[T: TimestampEntity](
    MySQLRepositoryContract[T], TimestampRepositoryContract[T]
): ...


class MySQLPersistenceRepositoryContract[T: PersistenceEntity](
    MySQLIdentifiedRepositoryContract[T],
    MySQLTimestampRepositoryContract[T],
    PersistenceRepositoryContract[T],
): ...
