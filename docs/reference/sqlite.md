# sqlite

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.repositories.backends.sqlite`

### `SQLiteReader`

```python
class SQLiteReader(SQLiteReaderContract):
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        ...
```

### `SQLiteRepository`

```python
class SQLiteRepository[T: BaseEntity](SQLiteRepositoryContract[T]):
    table: type[T]
    def __init__(self, uow: SQLiteUnitOfWork):
        ...

    def _upsert_stmt(self, row: Mapping[str, Any], *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    async def upsert(self, data: T, *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> T:
        ...

    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Sequence[T]:
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> CTE:
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

### `SQLiteIdentifiedRepository`

```python
class SQLiteIdentifiedRepository[T: IdentifiedEntity](SQLiteRepository[T], SQLiteIdentifiedRepositoryContract[T]):
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

### `SQLiteTimestampRepository`

```python
class SQLiteTimestampRepository[T: TimestampEntity](SQLiteRepository[T], SQLiteTimestampRepositoryContract[T]):
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

### `SQLitePersistenceRepository`

```python
class SQLitePersistenceRepository[T: PersistenceEntity](SQLiteIdentifiedRepository[T], SQLiteTimestampRepository[T], SQLitePersistenceRepositoryContract[T]):
    def _time_query(self):
        ...
```
