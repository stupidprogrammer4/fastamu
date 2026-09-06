from typing import (
    Any,
    AsyncIterator,
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
    insert,
    inspect,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.engine import Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.base import Executable
from sqlmodel import col

from fastamu.common.errors.exceptions import ConflictException
from fastamu.common.models.base import (
    BaseIDModel,
    BaseIDTimestampModel,
    BaseModel,
    BaseTimestampModel,
)
from fastamu.common.schemas.dtos import SupportsToRow
from fastamu.common.schemas.results import PagedType
from fastamu.core import resources

from .dialects import get_dialect
from .uow import DBUnitOfWork


class DBReader:
    """Read side for code that owns no table.

    A context module pulls a handful of columns to feed its logic; it has no
    model to bind, so it takes the unit of work and nothing else. Everything a
    repository does on top of that is in ``DBRepository`` below.
    """

    def __init__(self, uow: DBUnitOfWork):
        self.session = uow.session
        self.dialect = get_dialect(self.session.get_bind().dialect.name)


class DBRepository[TModel: BaseModel](DBReader):
    """The write side, declared against a model and executed against a table.

    A repository names the **model** it serves — ``DBRepository[BrandModel]``
    — and finds the table itself. That keeps the persistence class out of every
    signature above it: a service asks for a `BrandModel` and gets one, whether
    the row came from `BrandTable` or was built by hand in a test.
    """

    __model__: type[TModel]
    __model_name__: str
    __table__: type[Any]

    _managed_columns = frozenset({"created_at", "updated_at"})

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", []):
            origin = get_origin(base)
            args = get_args(base)

            if not origin or not args:
                continue

            if isinstance(args[0], TypeVar):
                continue

            if isinstance(origin, type) and issubclass(origin, DBRepository):
                model_cls = args[0]
                cls.__model__ = model_cls
                cls.__model_name__ = model_cls.__name__.removesuffix("Model")
                break

    def __getattr__(self, name: str) -> Any:
        # resolved on first use, not at class creation: infra/tables.py is
        # imported by the bootstrapper, which may not have run when a
        # repository class is defined
        if name != "__table__":
            raise AttributeError(name)
        found = self._tabled(type(self).__model__)
        if found is None:
            raise AttributeError(
                f"{type(self).__name__} serves "
                f"{type(self).__model__.__name__}, which no table subclasses "
                f"— declare one in the module's infra/tables.py"
            )
        type(self).__table__ = found
        return found

    @classmethod
    def _tabled(cls, model: type) -> Any:
        """Find the table class that carries `model`, at any depth."""
        found = None
        for sub in model.__subclasses__():
            if getattr(sub, "model_config", {}).get("table"):
                found = sub
                break
            deeper = cls._tabled(sub)
            if deeper is not None:
                found = deeper
                break
        return found

    def _as_conflict(self, error: IntegrityError) -> ConflictException | None:
        unique_dict = self.dialect.unique_values(error)
        if unique_dict is None:
            return None
        name = self.__model_name__
        return ConflictException(
            message=f"Another {name} already holds these values",
            message_code=resources.CONFILICT_ERROR.format(name.lower()),
            unique_dict=unique_dict,
        )

    async def _write(self, stmt: Executable) -> Result[Any]:
        """Run a statement that writes, answering a duplicate with a 409.

        Every write goes through here so no repository has to remember: a
        unique index is a rule the client broke, and it should read as one
        (409, naming the fields) instead of the 500 an untranslated
        `IntegrityError` becomes.

        Args:
            stmt (Executable): The INSERT/UPDATE/DELETE to run.
        Returns:
            (Result[Any]): The statement's result.
        Raises:
            ConflictException: A unique index refused the write.
        """
        try:
            result = await self.session.execute(stmt)
        except IntegrityError as error:
            conflict = self._as_conflict(error)
            if conflict is None:
                raise
            raise conflict from error
        return result

    def _identity_filter(self, rows):
        columns = list(inspect(self.__table__).primary_key)
        if not columns:
            raise ValueError("Repository tables require a primary key")
        if len(columns) == 1:
            return columns[0].in_(
                [getattr(row, columns[0].key) for row in rows]
            )
        return tuple_(*columns).in_(
            [
                tuple(getattr(row, column.key) for column in columns)
                for row in rows
            ]
        )

    async def _reload(self, rows):
        if not rows:
            return []
        result = await self.session.execute(
            select(self.__table__)
            .where(self._identity_filter(rows))
            .execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def _insert_rows(self, rows):
        if self.dialect.returning:
            result = await self._write(
                insert(self.__table__).values(rows).returning(self.__table__)
            )
            return result.scalars().all()
        # ORM collects generated primary keys without assuming contiguous IDs.
        objects = [self.__table__(**row) for row in rows]
        self.session.add_all(objects)
        try:
            await self.session.flush()
        except IntegrityError as error:
            conflict = self._as_conflict(error)
            if conflict is None:
                raise
            raise conflict from error
        return await self._reload(objects)

    async def _mutate(self, stmt, where, *, deleting=False):
        if self.dialect.returning:
            result = await self._write(stmt.returning(self.__table__))
            return result.scalars().all()
        selected = await self.session.execute(
            select(self.__table__).where(where).with_for_update()
        )
        rows = selected.scalars().all()
        if not rows:
            return []
        await self._write(
            stmt.where(self._identity_filter(rows)).execution_options(
                synchronize_session=False
            )
        )
        return rows if deleting else await self._reload(rows)

    async def _upsert_rows(self, rows, keys):
        if not keys:
            raise ValueError("Upsert requires conflict keys")
        if any(key not in row for row in rows for key in keys):
            raise ValueError("Upsert rows must supply every conflict key")
        stmt = self.dialect.upsert(self.__table__, rows, keys)
        if self.dialect.returning:
            result = await self._write(
                stmt.returning(self.__table__).execution_options(
                    populate_existing=True
                )
            )
            return result.scalars().all()
        await self._write(stmt)
        where = or_(
            *(
                and_(
                    *(getattr(self.__table__, key) == row[key] for key in keys)
                )
                for row in rows
            )
        )
        result = await self.session.execute(
            select(self.__table__)
            .where(where)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def upsert_rows(self, data, index_elements):
        if not data:
            return []
        return await self._upsert_rows(
            self._rows(data), [self._column_key(key) for key in index_elements]
        )

    async def bulk_update_rows(self, data, key):
        if not data:
            return []
        rows = self._rows(data)
        key_name = self._column_key(key)
        keys = [row[key_name] for row in rows]
        if len(set(keys)) != len(keys):
            raise ValueError("Bulk update keys must be unique")
        stmt = self.dialect.bulk_update(
            self.__table__, rows, key_name, self._managed_columns
        )
        return await self._mutate(
            stmt, getattr(self.__table__, key_name).in_(keys)
        )

    async def create(self, data: TModel) -> TModel:
        """
        Create a new record.

        Args:
            data (TModel): A SQLModel carrying the fields for the new record.
        Returns:
            (TModel): Created record.
        """
        rows = await self._insert_rows([data.to_row()])
        return rows[0]

    async def bulk_create(self, data: Sequence[TModel]) -> Sequence[TModel]:
        """
        Create multiple records.

        Args:
            data (Sequence[TModel]): SQLModels carrying the fields for new
                records.
        Returns:
            (Sequence[TModel]): Created records.
        """
        if not data:
            return []
        return await self._insert_rows([row.to_row() for row in data])

    async def get_all_stream(
        self, yield_per: int = 100
    ) -> AsyncIterator[TModel]:
        """
        Stream all records.

        Args:
            yield_per (int): Number of records to fetch per batch.
        Returns:
            (AsyncIterator[TModel]): Async iterator of records.
        """
        stmt = select(self.__table__).execution_options(yield_per=yield_per)
        stream = await self.session.stream_scalars(stmt)
        async for row in stream:
            yield row

    async def get_all(self) -> Sequence[TModel]:
        """
        Get all records.

        Returns:
            (Sequence[TModel]): All records.
        """
        stmt = select(self.__table__)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _paginate(
        self, stmt: Select[Any], offset: int, limit: int
    ) -> PagedType[TModel]:
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
            (PagedType[TModel]): The page rows and the total match count.
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
        if not self.dialect.returning:
            raise NotImplementedError(
                "Use upsert_rows() on dialects without RETURNING"
            )
        return stmt.returning(self.__table__)

    def _bulk_update_stmt(self, data, key):
        rows = self._rows(data)
        if not self.dialect.returning:
            raise NotImplementedError(
                "Use bulk_update_rows() on dialects without RETURNING"
            )
        return self.dialect.bulk_update(
            self.__table__, rows, self._column_key(key), self._managed_columns
        ).returning(self.__table__)

    @staticmethod
    def _column_key(element: Mapped[BaseModel]) -> str:
        """
        Resolve a column attribute's name.

        Args:
            element (Mapped[Any]): A model column attribute
                (``col(Model.field)``).
        Returns:
            (str): The underlying column key.
        """
        return element.key  # type: ignore


class DBIDRepository[TIDModel: BaseIDModel](DBRepository[TIDModel]):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)

    async def get_by_id(self, id: int) -> Optional[TIDModel]:
        """
        Get a record by ID.

        Args:
            id (int): ID of the record to retrieve.
        Returns:
            (Optional[TIDModel]): Found record or None.
        """
        stmt = select(self.__table__).where(col(self.__table__.id) == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_id(self, id: int) -> Optional[TIDModel]:
        """
        Delete a record by ID.

        Args:
            id (int): ID of the record to delete.
        Returns:
            (Optional[TIDModel]): Deleted record or None.
        """
        where = col(self.__table__.id) == id
        rows = await self._mutate(
            delete(self.__table__).where(where), where, deleting=True
        )
        return rows[0] if rows else None

    async def update_row_by_id(
        self, id: int, data: TIDModel
    ) -> Optional[TIDModel]:
        """
        Update a record by ID from a model instance.

        Only explicitly-set fields are written (``to_row`` excludes unset),
        so a partially-populated model acts as a patch.

        Args:
            id (int): ID of the record to update.
            data (TIDModel): A model whose set fields are written.
        Returns:
            (Optional[TIDModel]): Updated record or None.
        """
        row = await self.update_by_id(id, data.to_row())
        return row

    async def update_by_id(
        self, id: int, row: dict[str, Any]
    ) -> Optional[TIDModel]:
        """
        Update a record by ID from a column dict.

        Args:
            id (int): ID of the record to update.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (Optional[TIDModel]): Updated record or None.
        """
        where = col(self.__table__.id) == id
        rows = await self._mutate(
            update(self.__table__).where(where).values(**row), where
        )
        return rows[0] if rows else None

    async def get_by_ids(self, ids: list[int]) -> Sequence[TIDModel]:
        """
        Get multiple records by IDs.

        Args:
            ids (list[int]): List of record IDs to retrieve.
        Returns:
            (Sequence[TIDModel]): Found records.
        """
        stmt = select(self.__table__).where(col(self.__table__.id).in_(ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_by_ids(
        self, ids: Sequence[int], row: dict[str, Any]
    ) -> Sequence[TIDModel]:
        """
        Update multiple records by IDs.

        Args:
            ids (Sequence[int]): Sequence of record IDs to update.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (Sequence[TIDModel]): Updated records.
        """
        if not ids:
            return []
        where = col(self.__table__.id).in_(ids)
        return await self._mutate(
            update(self.__table__).where(where).values(**row), where
        )

    async def delete_by_ids(self, ids: Sequence[int]) -> Sequence[TIDModel]:
        """
        Delete multiple records by IDs.

        Args:
            ids (Sequence[int]): Sequence of record IDs to delete.
        Returns:
            (Sequence[TIDModel]): Deleted records.
        """
        if not ids:
            return []
        where = col(self.__table__.id).in_(ids)
        return await self._mutate(
            delete(self.__table__).where(where), where, deleting=True
        )

    async def upsert_by_id(self, id: int, row: dict[str, Any]) -> TIDModel:
        """
        Upsert a record by ID.

        Args:
            id (int): ID of the record to upsert.
            row (dict[str, Any]): Column values to write (from a validated
                DTO's ``to_row()``).
        Returns:
            (TIDModel): Created or updated record.
        """
        if "id" in row and row["id"] != id:
            raise ValueError("Conflicting id in upsert data")
        rows = await self._upsert_rows([dict(row, id=id)], ["id"])
        return rows[0]


class DBTimestampRepository[TTimestampModel: BaseTimestampModel](
    DBRepository[TTimestampModel]
):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)

    async def get_stream_by_date_range(
        self, start: str, end: str, yield_per: int = 100
    ) -> AsyncIterator[TTimestampModel]:
        """
        Stream records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
            yield_per (int): Number of records to fetch per batch.
        Returns:
            (AsyncIterator[TTimestampModel]): Async iterator of records.
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
    ) -> Sequence[TTimestampModel]:
        """
        Delete records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
        Returns:
            (Sequence[TTimestampModel]): Deleted records.
        """
        where = and_(
            col(self.__table__.created_at) >= start,
            col(self.__table__.created_at) <= end,
        )
        return await self._mutate(
            delete(self.__table__).where(where), where, deleting=True
        )

    async def update_by_date_range(
        self, start: str, end: str, data: BaseModel
    ) -> Sequence[TTimestampModel]:
        """
        Update records within a date range.

        Args:
            start (str): Start date in ISO format.
            end (str): End date in ISO format.
            data (BaseModel): A SQLModel carrying the fields to update.
        Returns:
            (Sequence[TTimestampModel]): Updated records.
        """
        where = and_(
            col(self.__table__.created_at) >= start,
            col(self.__table__.created_at) <= end,
        )
        return await self._mutate(
            update(self.__table__).where(where).values(**data.to_row()), where
        )


class DBTimestampIDRepository[TIDTimestampModel: BaseIDTimestampModel](
    DBIDRepository[TIDTimestampModel], DBTimestampRepository[TIDTimestampModel]
):
    def __init__(self, uow: DBUnitOfWork):
        super().__init__(uow)
