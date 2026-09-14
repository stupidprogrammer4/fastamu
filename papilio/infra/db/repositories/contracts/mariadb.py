"""MariaDB repository capabilities and exact native result types."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Subquery

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
from papilio.infra.db.uow import MariaDBUnitOfWork


class MariaDBReaderContract(ReaderContract[MariaDBUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MariaDBUnitOfWork) -> None: ...


class MariaDBRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MariaDBUnitOfWork) -> None: ...

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
    ) -> T: ...

    @abstractmethod
    async def bulk_upsert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Sequence[T]: ...


class MariaDBIdentifiedRepositoryContract[T: IdentifiedEntity](
    MariaDBRepositoryContract[T], IdentifiedRepositoryContract[T]
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


class MariaDBTimestampRepositoryContract[T: TimestampEntity](
    MariaDBRepositoryContract[T], TimestampRepositoryContract[T]
): ...


class MariaDBPersistenceRepositoryContract[T: PersistenceEntity](
    MariaDBIdentifiedRepositoryContract[T],
    MariaDBTimestampRepositoryContract[T],
    PersistenceRepositoryContract[T],
): ...
