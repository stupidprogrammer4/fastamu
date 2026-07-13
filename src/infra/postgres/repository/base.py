from typing import (
    Any,
    AsyncIterator,
    Generic,
    Optional,
    Sequence,
    TypeVar,
    get_args,
    get_origin
)

from ..uow import PGUnitOfWork
from ..models.typing import (
    TModel,
    TIDModel,
    TTimestampModel,
    TIDTimestampModel
)
from ..models.base import BaseModel
from src.common.bases.dtos import SupportsToRow
from src.common.bases.results import PagedType
from sqlalchemy import (
    Select,
    Values,
    column,
    func,
    inspect,
    literal,
    select,
    update,
    delete,
    insert,
    values
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Mapped
from sqlalchemy.sql.dml import ReturningInsert, ReturningUpdate
from sqlmodel import col


T = TypeVar("T", bound=BaseModel)

class PGRepository(Generic[TModel]):
    __model__: type[TModel]
    __model_name__: str

    _managed_columns = frozenset({"created_at", "updated_at"})

    def __init__(self, uow: PGUnitOfWork):
        self.session = uow.session

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", []):
            origin = get_origin(base)
            args = get_args(base)

            if not origin or not args:
                continue

            if isinstance(args[0], TypeVar):
                continue

            if isinstance(origin, type) and issubclass(origin, PGRepository):
                model_cls = args[0]
                cls.__model__ = model_cls
                cls.__model_name__ = model_cls.__name__.removesuffix("Model")
                break

    async def create(self, data: TModel) -> TModel:
        """
            Create a new record.

            Args:
                data (TModel): A SQLModel carrying the fields for the new record.
            Returns:
                (TModel): Created record.
        """
        stmt = insert(self.__model__).values(**data.to_row()).returning(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def bulk_create(self, data: Sequence[TModel]) -> Sequence[TModel]:
        """
            Create multiple records.

            Args:
                data (Sequence[TModel]): SQLModels carrying the fields for new records.
            Returns:
                (Sequence[TModel]): Created records.
        """
        stmt = insert(self.__model__).values([d.to_row() for d in data]).returning(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_all_stream(self, yield_per: int = 100) -> AsyncIterator[TModel]:
        """
            Stream all records.

            Args:
                yield_per (int): Number of records to fetch per batch.
            Returns:
                (AsyncIterator[TModel]): Async iterator of records.
        """
        stmt = select(self.__model__).execution_options(yield_per=yield_per)
        stream = await self.session.stream_scalars(stmt)
        async for row in stream:
            yield row

    async def get_all(self) -> Sequence[TModel]:
        """
            Get all records.

            Returns:
                (Sequence[TModel]): All records.
        """
        stmt = select(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def _paginate(
        self, stmt: Select[Any], offset: int, limit: int
    ) -> PagedType[TModel]:
        """Run one filtered/ordered ``select(Model)`` as a page, counting the
        whole match set in the same statement.

        A ``count(*) OVER ()`` window carries the pre-limit total alongside the
        page rows, so the page and its total come back in a single query. The
        base select must select the model only and already carry its filters
        and ordering; offset/limit are applied here.

        Args:
            stmt (Select[Any]): The filtered, ordered ``select(Model)``.
            offset (int): Rows to skip.
            limit (int): Rows to return.
        Returns:
            (PagedType[TModel]): The page rows and the total match count.
        """
        total = func.count().over().label("total")
        paged = stmt.add_columns(total).offset(offset).limit(limit)
        result = await self.session.execute(paged)
        rows = result.unique().all()
        items = [row[0] for row in rows]
        total_items = rows[0][-1] if rows else 0
        return PagedType(items=items, total_items=total_items)

    def _values_grid(self, data: Sequence[SupportsToRow]) -> Values:
        """
            Build a typed VALUES grid from model rows for FROM-clause joins.

            Args:
                data (Sequence[SupportsToRow]): Non-empty rows (models or DTOs);
                    their set columns and the model's column types define the grid.
            Returns:
                (Values): VALUES construct exposing its columns via ``.c``.
        """
        mapper = inspect(self.__model__)
        rows = [row.to_row(exclude_unset=True) for row in data]
        names = list(rows[0].keys())
        types = {name: mapper.columns[name].type for name in names}
        return values(
            *(column(name, types[name]) for name in names),
            name="bulk_values",
        ).data([
            tuple(literal(row[name], types[name]) for name in names)
            for row in rows
        ])

    def _upsert_stmt(
        self,
        data: SupportsToRow | Sequence[SupportsToRow],
        index_elements: Sequence[Mapped[Any]]
    ) -> ReturningInsert[tuple[TModel]]:
        """
            Build an INSERT ... ON CONFLICT DO UPDATE ... RETURNING the model.

            Args:
                data (SupportsToRow | Sequence[SupportsToRow]): One row or many to insert.
                index_elements (Sequence[Mapped[Any]]): Conflict-target columns as
                    model attributes (e.g. ``col(Model.field)``). On conflict every
                    inserted column except these is refreshed from the proposed row.
            Returns:
                (ReturningInsert[tuple[TModel]]): The upsert statement.
        """
        conflict_keys = {self._column_key(element) for element in index_elements}
        rows = [data.to_row()] if isinstance(data, SupportsToRow) else [row.to_row() for row in data]
        base = pg_insert(self.__model__).values(rows)
        set_keys = [name for name in rows[0] if name not in conflict_keys]
        set_: dict[str, Any] = {name: base.excluded[name] for name in set_keys}
        stmt = (
            base
            .on_conflict_do_update(index_elements=list(index_elements), set_=set_)
            .returning(self.__model__)
        )
        return stmt

    def _bulk_update_stmt(
        self,
        data: Sequence[SupportsToRow],
        key: Mapped[Any],
    ) -> ReturningUpdate[tuple[TModel]]:
        """
            Build a bulk UPDATE that sets each row from a typed VALUES grid.

            One statement updates every row: the grid is joined to the table on
            ``key`` and the set columns are read per-row from the grid.

            Args:
                data (Sequence[SupportsToRow]): Non-empty rows (models or DTOs)
                    carrying the key plus the columns to write.
                key (Mapped[Any]): The match column (e.g. ``col(Model.metal_id)``).
                    Every grid column except the key and DB-managed timestamps is
                    written per-row.
            Returns:
                (ReturningUpdate[tuple[TModel]]): The bulk update statement.
        """
        grid = self._values_grid(data)
        key_name = self._column_key(key)
        skip = self._managed_columns | {key_name}
        set_keys = [name for name in grid.c.keys() if name not in skip]
        stmt = (
            update(self.__model__)
            .where(key == grid.c[key_name])
            .values({name: grid.c[name] for name in set_keys})
            .returning(self.__model__)
        )
        return stmt

    @staticmethod
    def _column_key(element: Mapped[BaseModel]) -> str:
        """
            Resolve a column attribute's name.

            Args:
                element (Mapped[Any]): A model column attribute (``col(Model.field)``).
            Returns:
                (str): The underlying column key.
        """
        return element.key # type: ignore


class PGIDRepository(PGRepository[TIDModel]):
    def __init__(self, uow: PGUnitOfWork):
        super().__init__(uow)


    async def get_by_id(self, id: int) -> Optional[TIDModel]:
        """
            Get a record by ID.

            Args:
                id (int): ID of the record to retrieve.
            Returns:
                (Optional[TIDModel]): Found record or None.
        """
        stmt = select(self.__model__).where(col(self.__model__.id) == id)
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
        stmt = delete(self.__model__).where(col(self.__model__.id) == id).returning(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_row_by_id(self, id: int, data: TIDModel) -> Optional[TIDModel]:
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

    async def update_by_id(self, id: int, row: dict[str, Any]) -> Optional[TIDModel]:
        """
            Update a record by ID from a column dict.

            Args:
                id (int): ID of the record to update.
                row (dict[str, Any]): Column values to write (from a validated
                    DTO's ``to_row()``).
            Returns:
                (Optional[TIDModel]): Updated record or None.
        """
        stmt = (
            update(self.__model__)
            .where(col(self.__model__.id) == id)
            .values(**row)
            .returning(self.__model__)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: list[int]) -> Sequence[TIDModel]:
        """
            Get multiple records by IDs.

            Args:
                ids (list[int]): List of record IDs to retrieve.
            Returns:
                (Sequence[TIDModel]): Found records.
        """
        stmt = select(self.__model__).where(col(self.__model__.id).in_(ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_by_ids(self, ids: Sequence[int], row: dict[str, Any]) -> Sequence[TIDModel]:
        """
            Update multiple records by IDs.

            Args:
                ids (Sequence[int]): Sequence of record IDs to update.
                row (dict[str, Any]): Column values to write (from a validated
                    DTO's ``to_row()``).
            Returns:
                (Sequence[TIDModel]): Updated records.
        """
        stmt = (
            update(self.__model__)
            .where(col(self.__model__.id).in_(ids))
            .values(**row)
            .returning(self.__model__)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def delete_by_ids(self, ids: Sequence[int]) -> Sequence[TIDModel]:
        """
            Delete multiple records by IDs.

            Args:
                ids (Sequence[int]): Sequence of record IDs to delete.
            Returns:
                (Sequence[TIDModel]): Deleted records.
        """
        stmt = delete(self.__model__).where(col(self.__model__.id).in_(ids)).returning(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalars().all()

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
        stmt = pg_insert(self.__model__).values(id=id, **row).on_conflict_do_update(
            index_elements=[col(self.__model__.id)],
            set_=row
        ).returning(self.__model__)
        result = await self.session.execute(stmt)
        return result.scalar_one()


class PGTimestampRepository(PGRepository[TTimestampModel]):
    def __init__(self, uow: PGUnitOfWork):
        super().__init__(uow)

    async def get_stream_by_date_range(
        self,
        start: str,
        end: str,
        yield_per: int = 100
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
            select(self.__model__)
            .where(col(self.__model__.created_at) >= start, col(self.__model__.created_at) <= end)
            .execution_options(yield_per=yield_per)
        )
        stream = await self.session.stream_scalars(stmt)
        async for row in stream:
            yield row

    async def delete_by_date_range(
        self,
        start: str,
        end: str
    ) -> Sequence[TTimestampModel]:
        """
            Delete records within a date range.

            Args:
                start (str): Start date in ISO format.
                end (str): End date in ISO format.
            Returns:
                (Sequence[TTimestampModel]): Deleted records.
        """
        stmt = (
            delete(self.__model__)
            .where(col(self.__model__.created_at) >= start, col(self.__model__.created_at) <= end)
            .returning(self.__model__)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_by_date_range(
        self,
        start: str,
        end: str,
        data: BaseModel
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
        stmt = (
            update(self.__model__)
            .where(col(self.__model__.created_at) >= start, col(self.__model__.created_at) <= end)
            .values(**data.to_row())
            .returning(self.__model__)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PGTimestampIDRepository(
    PGIDRepository[TIDTimestampModel],
    PGTimestampRepository[TIDTimestampModel]
):
    def __init__(self, uow: PGUnitOfWork):
        super().__init__(uow)