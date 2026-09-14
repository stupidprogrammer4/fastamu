"""Oracle repository capabilities and exact native result types."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Subquery

from papilio.infra.db.repositories.contracts.base import (
    IdentifiedRepositoryContract,
    PersistenceRepositoryContract,
    ReaderContract,
    RepositoryContract,
    TimestampRepositoryContract,
)
from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.uow import OracleUnitOfWork


class OracleReaderContract(ReaderContract[OracleUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: OracleUnitOfWork) -> None: ...


class OracleRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    async def create(self, data: T) -> T: ...

    @abstractmethod
    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]: ...

    @abstractmethod
    def __init__(self, uow: OracleUnitOfWork) -> None: ...

    @abstractmethod
    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Mapping[str, ColumnClause[Any]],
        name: str = "incoming",
    ) -> Subquery: ...


class OracleIdentifiedRepositoryContract[T: IdentifiedEntity](
    OracleRepositoryContract[T], IdentifiedRepositoryContract[T]
):
    @abstractmethod
    async def remove_by_id(self, id: int) -> T | None: ...

    @abstractmethod
    async def remove_by_ids(self, ids: Sequence[int]) -> Sequence[T]: ...

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


class OracleTimestampRepositoryContract[T: TimestampEntity](
    OracleRepositoryContract[T], TimestampRepositoryContract[T]
): ...


class OraclePersistenceRepositoryContract[T: PersistenceEntity](
    OracleIdentifiedRepositoryContract[T],
    OracleTimestampRepositoryContract[T],
    PersistenceRepositoryContract[T],
): ...
