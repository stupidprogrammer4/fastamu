from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Optional,
    Sequence,
    TypeVar,
    get_args,
    get_origin,
)

from sqlalchemy import (
    Select,
    and_,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.engine import Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.base import Executable
from sqlmodel import col

from fastamu.common.errors.exceptions import ConflictException
from fastamu.common.models.entities import (
    BaseEntity,
    BaseIDEntity,
    BaseIDTimestampEntity,
    BaseTimestampEntity,
)
from fastamu.common.schemas.dtos import SupportsToRow
from fastamu.common.schemas.results import PagedType
from fastamu.core import resources

from .table import TABLES
from .uow import DBUnitOfWork, ReturningUnitOfWork


class DBReader:
    """Read side for code that owns no table.

    A context module pulls a handful of columns to feed its logic; it has no
    model to bind, so it takes the unit of work and nothing else. Everything a
    repository does on top of that is in ``DBRepository`` below.
    """

    def __init__(self, uow: DBUnitOfWork):
        self.uow = uow
        self.session = uow.session
        self.dialect = uow.db.adapter


class DBRepository[TEntity: BaseEntity](DBReader):
    """The write side, declared against the entity it answers with.

    ``DBIDRepository[BrandEntity]`` — signatures above infra never see the
    table, and the table it writes is bound once, at class creation.
    """

    __entity__: type[TEntity]
    __model_name__: str
    __table__: type[Any]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", []):
            origin = get_origin(base)
            args = get_args(base)

            if not origin or not args or isinstance(args[0], TypeVar):
                continue

            if isinstance(origin, type) and issubclass(origin, DBRepository):
                entity = args[0]
                table = TABLES.get(entity)
                if table is None:
                    raise TypeError(
                        f"{entity.__name__} has no table — declare one in the "
                        "module's infra/tables.py"
                    )
                cls.__entity__ = entity
                cls.__model_name__ = entity.__name__.removesuffix("Entity")
                cls.__table__ = table
                break

    def _as_conflict(self, error: IntegrityError) -> ConflictException | None:
        """Only a unique violation is the client's; the rest stay raw."""
        unique_dict = self.dialect.unique_values(error)
        conflict: ConflictException | None = None
        if unique_dict is not None:
            name = self.__model_name__
            conflict = ConflictException(
                message=f"Another {name} already holds these values",
                message_code=resources.CONFILICT_ERROR.format(name.lower()),
                unique_dict=unique_dict,
            )
        return conflict

    async def _written[T](self, write: Awaitable[T]) -> T:
        """Answer a duplicate with a 409 instead of an untranslated 500."""
        try:
            return await write
        except IntegrityError as error:
            conflict = self._as_conflict(error)
            if conflict is None:
                raise
            raise conflict from error

    async def _write(self, stmt: Executable) -> Result[Any]:
        return await self._written(self.session.execute(stmt))

    async def _insert_rows(self, rows):
        return await self._written(self.uow.insert(self.__table__, rows))

    async def _updated(self, stmt, where):
        return await self._written(
            self.uow.update(self.__table__, stmt, where)
        )

    async def _deleted(self, stmt, where):
        return await self._written(
            self.uow.delete(self.__table__, stmt, where)
        )

    async def _upsert_rows(self, rows, keys):
        if not keys:
            raise ValueError("Upsert requires conflict keys")
        if any(key not in row for row in rows for key in keys):
            raise ValueError("Upsert rows must supply every conflict key")
        statement = self.dialect.upsert(self.__table__, rows, keys)
        return await self._written(
            self.uow.upsert(self.__table__, statement, rows, keys)
        )

    async def upsert_rows(self, data, index_elements):
        upserted = []
        if data:
            upserted = await self._upsert_rows(
                self._rows(data),
                [self._column_key(key) for key in index_elements],
            )
        return upserted

    async def bulk_update_rows(self, data, key):
        updated = []
        if data:
            rows = self._rows(data)
            key_name = self._column_key(key)
            keys = [row[key_name] for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError("Bulk update keys must be unique")
            stmt = self.dialect.bulk_update(self.__table__, rows, key_name)
            updated = await self._updated(
                stmt, getattr(self.__table__, key_name).in_(keys)
            )
        return updated

    async def create(self, data: BaseEntity) -> TEntity:
        """
        Create a new record.

        Args:
            data (BaseEntity): A model carrying the fields for the new record.
        Returns:
            (TEntity): Created record.
        """
        rows = await self._insert_rows([data.to_row()])
        return rows[0]

    async def bulk_create(
        self, data: Sequence[BaseEntity]
    ) -> Sequence[TEntity]:
        """
        Create multiple records.

        Args:
            data (Sequence[BaseEntity]): Models carrying the fields for new
                records.
        Returns:
            (Sequence[TEntity]): Created records.
        """
        created: Sequence[TEntity] = []
        if data:
            created = await self._insert_rows([row.to_row() for row in data])
        return created

    async def get_all_stream(
        self, yield_per: int = 100
    ) -> AsyncIterator[TEntity]:
        """
        Stream all records.

        Args:
            yield_per (int): Number of records to fetch per batch.
        Returns:
            (AsyncIterator[TEntity]): Async iterator of records.
        """
        stmt = select(self.__table__).execution_options(yield_per=yield_per)
        stream = await self.session.stream_scalars(stmt)
        async for row in stream:
            yield row

    async def get_all(self) -> Sequence[TEntity]:
        """
        Get all records.

        Returns:
            (Sequence[TEntity]): All records.
        """
        stmt = select(self.__table__)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _paginate(
        self, stmt: Select[Any], offset: int, limit: int
    ) -> PagedType[TEntity]:
        """Run one filtered/ordered ``select(Model)`` as a page, plus a count
        of the whole match set.

        The count is its own statement — the filters wrapped in a subquery,
        with the ordering dropped because nothing is returned to order. The
        alternative, a ``count(*) OVER ()`` window riding along on the page,
        saves a round trip but has to be added to the caller's select: that
        turns every row into a ``(Model, total)`` tuple, so ``scalars()`` stops
        working, and any statement that is not a plain ``select(Model)`` —
        `DISTINCT`, a `GROUP BY`, an eager load — counts something other than
        what it returns. One extra query buys a paginator that behaves the same
        whatever statement it is handed.

        The base select must already carry its filters and ordering;
        offset/limit are applied here.

        Args:
            stmt (Select[Any]): The filtered, ordered ``select(Model)``.
            offset (int): Rows to skip.
            limit (int): Rows to return.
        Returns:
            (PagedType[TEntity]): The page rows and the total match count.
        """
        counted = select(func.count()).select_from(
            stmt.order_by(None).subquery()
        )
        total_items = await self.session.scalar(counted) or 0
        paged = stmt.offset(offset).limit(limit)
        result = await self.session.execute(paged)
        items = list(result.unique().scalars().all())
        return PagedType(items=items, total_items=total_items)

    @staticmethod
    def _rows(data: Sequence[SupportsToRow]) -> list[dict[str, Any]]:
        rows = [row.to_row(exclude_unset=True) for row in data]
        if not rows:
            raise ValueError("At least one row is required")
        if any(row.keys() != rows[0].keys() for row in rows):
            raise ValueError("Batch rows must have the same columns")
        return rows

    def _values_grid(self, data: Sequence[SupportsToRow]):
        return self.dialect.values_grid(self.__table__, self._rows(data))

    def _upsert_stmt(self, data, index_elements):
        rows = self._rows([data] if isinstance(data, SupportsToRow) else data)
        keys = [self._column_key(key) for key in index_elements]
        stmt = self.dialect.upsert(self.__table__, rows, keys)
        if not isinstance(self.uow, ReturningUnitOfWork):
            raise NotImplementedError(
                "Use upsert_rows() on dialects without RETURNING"
            )
        return stmt.returning(self.__table__)

    def _bulk_update_stmt(self, data, key):
        rows = self._rows(data)
        if not isinstance(self.uow, ReturningUnitOfWork):
            raise NotImplementedError(
                "Use bulk_update_rows() on dialects without RETURNING"
            )
        return self.dialect.bulk_update(
            self.__table__, rows, self._column_key(key)
        ).returning(self.__table__)

    @staticmethod
    def _column_key(element: Mapped[BaseEntity]) -> str:
        """Name the column a ``col(Model.field)`` attribute stands for."""
        return element.key  # type: ignore


class DBIDRepository[TEntity: BaseIDEntity](DBRepository[TEntity]):
    async def get_by_id(self, id: int) -> Optional[TEntity]:
        """
        Get a record by ID.

        Args:
            id (int): ID of the record to retrieve.
        Returns:
            (Optional[TEntity]): Found record or None.
        """
        stmt = select(self.__table__).where(col(self.__table__.id) == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_id(self, id: int) -> Optional[TEntity]:
        """
        Delete a record by ID.

        Args:
            id (int): ID of the record to delete.
        Returns:
            (Optional[TEntity]): Deleted record or None.
        """
        where = col(self.__table__.id) == id
        rows = await self._deleted(delete(self.__table__).where(where), where)
        return rows[0] if rows else None

    async def update_row_by_id(
        self, id: int, data: BaseEntity
    ) -> Optional[TEntity]:
        """
        Update a record by ID from a model instance.

        Only explicitly-set fields are written (``to_row`` excludes unset),
        so a partially-populated model acts as a patch.

        Args:
            id (int): ID of the record to update.
            data (BaseEntity): A model whose set fields are written.
        Returns:
            (Optional[TEntity]): Updated record or None.
        """
        row = await self.update_by_id(id, data.to_row())
        return row

    async def update_by_id(
        self, id: int, row: dict[str, Any]
    ) -> Optional[TEntity]:
        """
        Update a record by ID from a column dict.

        Args:
            id (int): ID of the record to update.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (Optional[TEntity]): Updated record or None.
        """
        where = col(self.__table__.id) == id
        rows = await self._updated(
            update(self.__table__).where(where).values(**row), where
        )
        return rows[0] if rows else None

    async def get_by_ids(self, ids: list[int]) -> Sequence[TEntity]:
        """
        Get multiple records by IDs.

        Args:
            ids (list[int]): List of record IDs to retrieve.
        Returns:
            (Sequence[TEntity]): Found records.
        """
        stmt = select(self.__table__).where(col(self.__table__.id).in_(ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_by_ids(
        self, ids: Sequence[int], row: dict[str, Any]
    ) -> Sequence[TEntity]:
        """
        Update multiple records by IDs.

        Args:
            ids (Sequence[int]): Sequence of record IDs to update.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (Sequence[TEntity]): Updated records.
        """
        updated: Sequence[TEntity] = []
        if ids:
            where = col(self.__table__.id).in_(ids)
            updated = await self._updated(
                update(self.__table__).where(where).values(**row), where
            )
        return updated

    async def delete_by_ids(self, ids: Sequence[int]) -> Sequence[TEntity]:
        """
        Delete multiple records by IDs.

        Args:
            ids (Sequence[int]): Sequence of record IDs to delete.
        Returns:
            (Sequence[TEntity]): Deleted records.
        """
        deleted: Sequence[TEntity] = []
        if ids:
            where = col(self.__table__.id).in_(ids)
            deleted = await self._deleted(
                delete(self.__table__).where(where), where
            )
        return deleted

    async def upsert_by_id(self, id: int, row: dict[str, Any]) -> TEntity:
        """
        Upsert a record by ID.

        Args:
            id (int): ID of the record to upsert.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (TEntity): Created or updated record.
        """
        if "id" in row and row["id"] != id:
            raise ValueError("Conflicting id in upsert data")
        rows = await self._upsert_rows([dict(row, id=id)], ["id"])
        return rows[0]


class DBTimestampRepository[TEntity: BaseTimestampEntity](
    DBRepository[TEntity]
):
    async def get_stream_by_date_range(
        self, start: str, end: str, yield_per: int = 100
    ) -> AsyncIterator[TEntity]:
        """
        Stream records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
            yield_per (int): Number of records to fetch per batch.
        Returns:
            (AsyncIterator[TEntity]): Async iterator of records.
        """
        stmt = (
            select(self.__table__)
            .where(
                col(self.__table__.created_at) >= start,
                col(self.__table__.created_at) <= end,
            )
            .execution_options(yield_per=yield_per)
        )
        stream = await self.session.stream_scalars(stmt)
        async for row in stream:
            yield row

    async def delete_by_date_range(
        self, start: str, end: str
    ) -> Sequence[TEntity]:
        """
        Delete records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
        Returns:
            (Sequence[TEntity]): Deleted records.
        """
        where = and_(
            col(self.__table__.created_at) >= start,
            col(self.__table__.created_at) <= end,
        )
        return await self._deleted(delete(self.__table__).where(where), where)

    async def update_by_date_range(
        self, start: str, end: str, data: BaseEntity
    ) -> Sequence[TEntity]:
        """
        Update records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
            data (BaseEntity): A SQLModel carrying the fields to update.
        Returns:
            (Sequence[TEntity]): Updated records.
        """
        where = and_(
            col(self.__table__.created_at) >= start,
            col(self.__table__.created_at) <= end,
        )
        return await self._updated(
            update(self.__table__).where(where).values(**data.to_row()), where
        )


class DBTimestampIDRepository[TEntity: BaseIDTimestampEntity](
    DBIDRepository[TEntity], DBTimestampRepository[TEntity]
):
    pass
