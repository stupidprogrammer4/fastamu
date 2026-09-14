# oracle

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

Shared implementations: [repository base](repository-base.md). Abstract obligations: [backend contracts](contracts.md).

## `papilio.infra.db.repositories.backends.oracle`

### `OracleReader`

```python
class OracleReader(Reader[OracleUnitOfWork], OracleReaderContract):

    def __init__(self, uow: OracleUnitOfWork) -> None:
        ...
```

### `OracleRepository`

```python
class OracleRepository[T: BaseEntity](Repository[T, OracleUnitOfWork], OracleRepositoryContract[T]):

    def __init__(self, uow: OracleUnitOfWork):
        ...

    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...

    async def create(self, data: T) -> T:
        ...

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        ...
```

### `OracleIdentifiedRepository`

```python
class OracleIdentifiedRepository[T: IdentifiedEntity](OracleRepository[T], IdentifiedRepository[T, OracleUnitOfWork], OracleIdentifiedRepositoryContract[T]):

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

### `OracleTimestampRepository`

```python
class OracleTimestampRepository[T: TimestampEntity](OracleRepository[T], TimestampRepository[T, OracleUnitOfWork], OracleTimestampRepositoryContract[T]):
    ...
```

### `OraclePersistenceRepository`

```python
class OraclePersistenceRepository[T: PersistenceEntity](OracleIdentifiedRepository[T], OracleTimestampRepository[T], PersistenceRepository[T, OracleUnitOfWork], OraclePersistenceRepositoryContract[T]):
    ...
```
