# mssql

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

Shared implementations: [repository base](repository-base.md). Abstract obligations: [backend contracts](contracts.md).

## `papilio.infra.db.repositories.backends.mssql`

### `MSSQLReader`

```python
class MSSQLReader(Reader[MSSQLUnitOfWork], MSSQLReaderContract):

    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        ...
```

### `MSSQLRepository`

```python
class MSSQLRepository[T: BaseEntity](Repository[T, MSSQLUnitOfWork], MSSQLRepositoryContract[T]):

    def __init__(self, uow: MSSQLUnitOfWork):
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Values:
        ...

    async def create(self, data: T) -> T:
        ...

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        ...
```

### `MSSQLIdentifiedRepository`

```python
class MSSQLIdentifiedRepository[T: IdentifiedEntity](MSSQLRepository[T], IdentifiedRepository[T, MSSQLUnitOfWork], MSSQLIdentifiedRepositoryContract[T]):

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

### `MSSQLTimestampRepository`

```python
class MSSQLTimestampRepository[T: TimestampEntity](MSSQLRepository[T], TimestampRepository[T, MSSQLUnitOfWork], MSSQLTimestampRepositoryContract[T]):
    ...
```

### `MSSQLPersistenceRepository`

```python
class MSSQLPersistenceRepository[T: PersistenceEntity](MSSQLIdentifiedRepository[T], MSSQLTimestampRepository[T], PersistenceRepository[T, MSSQLUnitOfWork], MSSQLPersistenceRepositoryContract[T]):
    ...
```
