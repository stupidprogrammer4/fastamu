# mssql

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.repositories.backends.mssql`

### `MSSQLReader`

```python
class MSSQLReader(MSSQLReaderContract):
    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        ...
```

### `MSSQLRepository`

```python
class MSSQLRepository[T: BaseEntity](MSSQLRepositoryContract[T]):
    table: type[T]
    def __init__(self, uow: MSSQLUnitOfWork):
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Values:
        ...

    async def create(self, data: T) -> T:
        ...

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        ...

    async def get_all(self) -> Sequence[T]:
        ...

    def get_all_stream(self, batch_size: int=100) -> AsyncIterator[T]:
        ...
```

### `MSSQLIdentifiedRepository`

```python
class MSSQLIdentifiedRepository[T: IdentifiedEntity](MSSQLRepository[T], MSSQLIdentifiedRepositoryContract[T]):
    async def get_by_id(self, id: int) -> T | None:
        ...

    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        ...

    async def get_paged(self, limit: int, offset: int=0) -> PagedType[T]:
        ...

    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> T | None:
        ...

    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    async def update_row_by_id(self, id: int, data: T) -> T | None:
        ...

    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...

    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Sequence[T]:
        ...

    async def remove_by_id(self, id: int) -> int:
        ...

    async def remove_by_ids(self, ids: Sequence[int]) -> int:
        ...
```

### `MSSQLTimestampRepository`

```python
class MSSQLTimestampRepository[T: TimestampEntity](MSSQLRepository[T], MSSQLTimestampRepositoryContract[T]):
    def _time_query(self):
        ...

    def _stream_time(self, condition, batch_size: int) -> AsyncIterator[T]:
        ...

    async def _page_time(self, condition, limit: int, offset: int) -> PagedType[T]:
        ...

    def get_stream_range(self, start: datetime, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_range(self, start: datetime, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_gt(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_gt(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_ge(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_ge(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_lt(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_lt(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_le(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_le(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...
```

### `MSSQLPersistenceRepository`

```python
class MSSQLPersistenceRepository[T: PersistenceEntity](MSSQLIdentifiedRepository[T], MSSQLTimestampRepository[T], MSSQLPersistenceRepositoryContract[T]):
    def _time_query(self):
        ...
```
