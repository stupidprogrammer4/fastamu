# sqlite

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

Shared implementations: [repository base](repository-base.md). Abstract obligations: [backend contracts](contracts.md).

## `papilio.infra.db.repositories.backends.sqlite`

### `SQLiteReader`

```python
class SQLiteReader(Reader[SQLiteUnitOfWork], SQLiteReaderContract):

    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        ...
```

### `SQLiteRepository`

```python
class SQLiteRepository[T: BaseEntity](Repository[T, SQLiteUnitOfWork], SQLiteRepositoryContract[T]):

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
```

### `SQLiteIdentifiedRepository`

```python
class SQLiteIdentifiedRepository[T: IdentifiedEntity](SQLiteRepository[T], IdentifiedRepository[T, SQLiteUnitOfWork], SQLiteIdentifiedRepositoryContract[T]):

    async def remove_by_id(self, id: int) -> T | None:
        ...

    async def remove_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
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
```

### `SQLiteTimestampRepository`

```python
class SQLiteTimestampRepository[T: TimestampEntity](SQLiteRepository[T], TimestampRepository[T, SQLiteUnitOfWork], SQLiteTimestampRepositoryContract[T]):
    ...
```

### `SQLitePersistenceRepository`

```python
class SQLitePersistenceRepository[T: PersistenceEntity](SQLiteIdentifiedRepository[T], SQLiteTimestampRepository[T], PersistenceRepository[T, SQLiteUnitOfWork], SQLitePersistenceRepositoryContract[T]):
    ...
```
