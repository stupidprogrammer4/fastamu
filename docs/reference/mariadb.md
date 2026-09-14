# mariadb

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

Shared implementations: [repository base](repository-base.md). Abstract obligations: [backend contracts](contracts.md).

## `papilio.infra.db.repositories.backends.mariadb`

### `MariaDBReader`

```python
class MariaDBReader(Reader[MariaDBUnitOfWork], MariaDBReaderContract):

    def __init__(self, uow: MariaDBUnitOfWork) -> None:
        ...
```

### `MariaDBRepository`

```python
class MariaDBRepository[T: BaseEntity](Repository[T, MariaDBUnitOfWork], MariaDBRepositoryContract[T]):

    def __init__(self, uow: MariaDBUnitOfWork):
        ...

    def _upsert_stmt(self, row: Mapping[str, Any], *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    async def upsert(self, data: T, *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> T:
        ...

    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Sequence[T]:
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...

    async def create(self, data: T) -> T:
        ...

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        ...
```

### `MariaDBIdentifiedRepository`

```python
class MariaDBIdentifiedRepository[T: IdentifiedEntity](MariaDBRepository[T], IdentifiedRepository[T, MariaDBUnitOfWork], MariaDBIdentifiedRepositoryContract[T]):

    async def remove_by_id(self, id: int) -> T | None:
        ...

    async def remove_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        ...

    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> int:
        ...

    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> int:
        ...

    async def update_row_by_id(self, id: int, data: T) -> int:
        ...

    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...

    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> int:
        ...
```

### `MariaDBTimestampRepository`

```python
class MariaDBTimestampRepository[T: TimestampEntity](MariaDBRepository[T], TimestampRepository[T, MariaDBUnitOfWork], MariaDBTimestampRepositoryContract[T]):
    ...
```

### `MariaDBPersistenceRepository`

```python
class MariaDBPersistenceRepository[T: PersistenceEntity](MariaDBIdentifiedRepository[T], MariaDBTimestampRepository[T], PersistenceRepository[T, MariaDBUnitOfWork], MariaDBPersistenceRepositoryContract[T]):
    ...
```
