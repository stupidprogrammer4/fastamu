"""MSSQL repository capabilities and exact native result types."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Values

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
from fastamu.infra.db.uow import MSSQLUnitOfWork


class MSSQLReaderContract(ReaderContract[MSSQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MSSQLUnitOfWork) -> None: ...


class MSSQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MSSQLUnitOfWork) -> None: ...

    @abstractmethod
    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Mapping[str, ColumnClause[Any]],
        name: str = "incoming",
    ) -> Values: ...


class MSSQLIdentifiedRepositoryContract[T: IdentifiedEntity](
    MSSQLRepositoryContract[T], IdentifiedRepositoryContract[T]
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

    @abstractmethod
    async def bulk_update(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> Sequence[T]: ...

    @abstractmethod
    def _bulk_update_stmt(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> Update: ...


class MSSQLTimestampRepositoryContract[T: TimestampEntity](
    MSSQLRepositoryContract[T], TimestampRepositoryContract[T]
): ...


class MSSQLPersistenceRepositoryContract[T: PersistenceEntity](
    MSSQLIdentifiedRepositoryContract[T],
    MSSQLTimestampRepositoryContract[T],
    PersistenceRepositoryContract[T],
): ...
