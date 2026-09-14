# mysql

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

Shared implementations: [repository base](repository-base.md). Abstract obligations: [backend contracts](contracts.md).

## `papilio.infra.db.repositories.backends.mysql`

### `MySQLReader`

```python
class MySQLReader(Reader[MySQLUnitOfWork], MySQLReaderContract):

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        ...
```

### `MySQLRepository`

```python
class MySQLRepository[T: BaseEntity](Repository[T, MySQLUnitOfWork], MySQLRepositoryContract[T]):

    def __init__(self, uow: MySQLUnitOfWork):
        ...

    def _upsert_stmt(self, row: Mapping[str, Any], *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    async def upsert(self, data: T, *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> int:
        ...

    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> int:
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...

    async def create(self, data: T) -> T:
        ...

    def _bulk_insert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]]) -> Insert:
        ...

    async def bulk_insert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]]) -> int:
        ...
```

### `MySQLIdentifiedRepository`

```python
class MySQLIdentifiedRepository[T: IdentifiedEntity](MySQLRepository[T], IdentifiedRepository[T, MySQLUnitOfWork], MySQLIdentifiedRepositoryContract[T]):

    async def remove_by_id(self, id: int) -> int:
        ...

    async def remove_by_ids(self, ids: Sequence[int]) -> int:
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

### `MySQLTimestampRepository`

```python
class MySQLTimestampRepository[T: TimestampEntity](MySQLRepository[T], TimestampRepository[T, MySQLUnitOfWork], MySQLTimestampRepositoryContract[T]):
    ...
```

### `MySQLPersistenceRepository`

```python
class MySQLPersistenceRepository[T: PersistenceEntity](MySQLIdentifiedRepository[T], MySQLTimestampRepository[T], PersistenceRepository[T, MySQLUnitOfWork], MySQLPersistenceRepositoryContract[T]):
    ...
```
