# Repository contracts

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.repositories.contracts.base`

### `ReaderContract`

```python
class ReaderContract[U: UnitOfWork](ABC):
    uow: U
    @abstractmethod
    def __init__(self, uow: U) -> None:
        ...
```

### `RepositoryContract`

```python
class RepositoryContract[T: BaseEntity](ABC):
    table: type[T]
    @abstractmethod
    async def create(self, data: T) -> T:
        ...

    @abstractmethod
    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        ...

    @abstractmethod
    async def get_all(self) -> Sequence[T]:
        ...

    @abstractmethod
    def get_all_stream(self, batch_size: int=100) -> AsyncIterator[T]:
        ...
```

### `IdentifiedRepositoryContract`

```python
class IdentifiedRepositoryContract[T: IdentifiedEntity](RepositoryContract[T]):
    @abstractmethod
    async def get_by_id(self, id: int) -> T | None:
        ...

    @abstractmethod
    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        ...

    @abstractmethod
    async def get_paged(self, limit: int, offset: int=0) -> PagedType[T]:
        ...

    @abstractmethod
    async def remove_by_id(self, id: int) -> int:
        ...

    @abstractmethod
    async def remove_by_ids(self, ids: Sequence[int]) -> int:
        ...
```

### `TimestampRepositoryContract`

```python
class TimestampRepositoryContract[T: TimestampEntity](RepositoryContract[T]):
    @abstractmethod
    def get_stream_range(self, start: datetime, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def get_paged_range(self, start: datetime, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    @abstractmethod
    def get_stream_gt(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def get_paged_gt(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    @abstractmethod
    def get_stream_ge(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def get_paged_ge(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    @abstractmethod
    def get_stream_lt(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def get_paged_lt(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    @abstractmethod
    def get_stream_le(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def get_paged_le(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...
```

### `PersistenceRepositoryContract`

```python
class PersistenceRepositoryContract[T: PersistenceEntity](IdentifiedRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.mariadb`

### `MariaDBReaderContract`

```python
class MariaDBReaderContract(ReaderContract[MariaDBUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MariaDBUnitOfWork) -> None:
        ...
```

### `MariaDBRepositoryContract`

```python
class MariaDBRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MariaDBUnitOfWork) -> None:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...

    @abstractmethod
    def _upsert_stmt(self, row: Mapping[str, Any], *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    async def upsert(self, data: T, *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> T:
        ...

    @abstractmethod
    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Sequence[T]:
        ...
```

### `MariaDBIdentifiedRepositoryContract`

```python
class MariaDBIdentifiedRepositoryContract[T: IdentifiedEntity](MariaDBRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> int:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> int:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> int:
        ...

    @abstractmethod
    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> int:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...
```

### `MariaDBTimestampRepositoryContract`

```python
class MariaDBTimestampRepositoryContract[T: TimestampEntity](MariaDBRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `MariaDBPersistenceRepositoryContract`

```python
class MariaDBPersistenceRepositoryContract[T: PersistenceEntity](MariaDBIdentifiedRepositoryContract[T], MariaDBTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.mssql`

### `MSSQLReaderContract`

```python
class MSSQLReaderContract(ReaderContract[MSSQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        ...
```

### `MSSQLRepositoryContract`

```python
class MSSQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Values:
        ...
```

### `MSSQLIdentifiedRepositoryContract`

```python
class MSSQLIdentifiedRepositoryContract[T: IdentifiedEntity](MSSQLRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> T | None:
        ...

    @abstractmethod
    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Sequence[T]:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...
```

### `MSSQLTimestampRepositoryContract`

```python
class MSSQLTimestampRepositoryContract[T: TimestampEntity](MSSQLRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `MSSQLPersistenceRepositoryContract`

```python
class MSSQLPersistenceRepositoryContract[T: PersistenceEntity](MSSQLIdentifiedRepositoryContract[T], MSSQLTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.mysql`

### `MySQLReaderContract`

```python
class MySQLReaderContract(ReaderContract[MySQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        ...
```

### `MySQLRepositoryContract`

```python
class MySQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: MySQLUnitOfWork) -> None:
        ...

    @abstractmethod
    def _bulk_insert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]]) -> Insert:
        ...

    @abstractmethod
    async def bulk_insert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]]) -> int:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...

    @abstractmethod
    def _upsert_stmt(self, row: Mapping[str, Any], *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    async def upsert(self, data: T, *, update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> int:
        ...

    @abstractmethod
    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> int:
        ...
```

### `MySQLIdentifiedRepositoryContract`

```python
class MySQLIdentifiedRepositoryContract[T: IdentifiedEntity](MySQLRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> int:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> int:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> int:
        ...

    @abstractmethod
    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> int:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...
```

### `MySQLTimestampRepositoryContract`

```python
class MySQLTimestampRepositoryContract[T: TimestampEntity](MySQLRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `MySQLPersistenceRepositoryContract`

```python
class MySQLPersistenceRepositoryContract[T: PersistenceEntity](MySQLIdentifiedRepositoryContract[T], MySQLTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.oracle`

### `OracleReaderContract`

```python
class OracleReaderContract(ReaderContract[OracleUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: OracleUnitOfWork) -> None:
        ...
```

### `OracleRepositoryContract`

```python
class OracleRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: OracleUnitOfWork) -> None:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> Subquery:
        ...
```

### `OracleIdentifiedRepositoryContract`

```python
class OracleIdentifiedRepositoryContract[T: IdentifiedEntity](OracleRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> T | None:
        ...

    @abstractmethod
    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Sequence[T]:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...
```

### `OracleTimestampRepositoryContract`

```python
class OracleTimestampRepositoryContract[T: TimestampEntity](OracleRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `OraclePersistenceRepositoryContract`

```python
class OraclePersistenceRepositoryContract[T: PersistenceEntity](OracleIdentifiedRepositoryContract[T], OracleTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.postgresql`

### `PostgreSQLReaderContract`

```python
class PostgreSQLReaderContract(ReaderContract[PostgreSQLUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: PostgreSQLUnitOfWork) -> None:
        ...
```

### `PostgreSQLRepositoryContract`

```python
class PostgreSQLRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: PostgreSQLUnitOfWork) -> None:
        ...

    @abstractmethod
    def _upsert_stmt(self, row: Mapping[str, Any], *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    async def upsert(self, data: T, *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> T:
        ...

    @abstractmethod
    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Sequence[T]:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Sequence[ColumnClause[Any]], name: str='incoming') -> Values:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, rows: Sequence[Mapping[str, Any]], *, key_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]]) -> Update:
        ...

    @abstractmethod
    async def bulk_update(self, rows: Sequence[Mapping[str, Any]], *, key_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]]) -> Sequence[T]:
        ...

    @abstractmethod
    async def get_one(self, *where: ColumnElement[bool]) -> T | None:
        ...

    @abstractmethod
    async def get_all(self, *where: ColumnElement[bool]) -> Sequence[T]:
        ...

    @abstractmethod
    def get_all_stream(self, batch_size: int=100, *, where: Sequence[ColumnElement[bool]]=()) -> AsyncIterator[T]:
        ...

    @abstractmethod
    async def exists(self, *where: ColumnElement[bool]) -> bool:
        ...

    @abstractmethod
    async def count(self, *where: ColumnElement[bool]) -> int:
        ...

    @abstractmethod
    async def get_page(self, *, order_by: Sequence[ColumnElement[Any]], limit: int, offset: int=0, where: Sequence[ColumnElement[bool]]=()) -> PagedType[T]:
        ...

    @abstractmethod
    async def update(self, where: ColumnElement[bool], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    @abstractmethod
    async def remove(self, where: ColumnElement[bool]) -> int:
        ...
```

### `PostgreSQLIdentifiedRepositoryContract`

```python
class PostgreSQLIdentifiedRepositoryContract[T: IdentifiedEntity](PostgreSQLRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> T | None:
        ...
```

### `PostgreSQLTimestampRepositoryContract`

```python
class PostgreSQLTimestampRepositoryContract[T: TimestampEntity](PostgreSQLRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `PostgreSQLPersistenceRepositoryContract`

```python
class PostgreSQLPersistenceRepositoryContract[T: PersistenceEntity](PostgreSQLIdentifiedRepositoryContract[T], PostgreSQLTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```

## `papilio.infra.db.repositories.contracts.sqlite`

### `SQLiteReaderContract`

```python
class SQLiteReaderContract(ReaderContract[SQLiteUnitOfWork]):
    @abstractmethod
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        ...
```

### `SQLiteRepositoryContract`

```python
class SQLiteRepositoryContract[T: BaseEntity](RepositoryContract[T]):
    @abstractmethod
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        ...

    @abstractmethod
    def _values_grid(self, rows: Sequence[Mapping[str, Any]], *, columns: Mapping[str, ColumnClause[Any]], name: str='incoming') -> CTE:
        ...

    @abstractmethod
    def _upsert_stmt(self, row: Mapping[str, Any], *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    def _bulk_upsert_stmt(self, rows: Sequence[Mapping[str, Any]], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Insert:
        ...

    @abstractmethod
    async def upsert(self, data: T, *, conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> T:
        ...

    @abstractmethod
    async def bulk_upsert(self, data: Sequence[T], *, insert_columns: Mapping[str, ColumnClause[Any]], conflict_columns: Sequence[ColumnClause[Any]], update_columns: Sequence[ColumnClause[Any]], changes: Mapping[ColumnClause[Any], Any] | None=None) -> Sequence[T]:
        ...
```

### `SQLiteIdentifiedRepositoryContract`

```python
class SQLiteIdentifiedRepositoryContract[T: IdentifiedEntity](SQLiteRepositoryContract[T], IdentifiedRepositoryContract[T]):
    @abstractmethod
    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> T | None:
        ...

    @abstractmethod
    async def update_by_ids(self, ids: Sequence[int], changes: Mapping[str, Any]) -> Sequence[T]:
        ...

    @abstractmethod
    async def update_row_by_id(self, id: int, data: T) -> T | None:
        ...

    @abstractmethod
    async def bulk_update(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Sequence[T]:
        ...

    @abstractmethod
    def _bulk_update_stmt(self, data: Sequence[T], *, update_columns: Mapping[str, ColumnClause[Any]]) -> Update:
        ...
```

### `SQLiteTimestampRepositoryContract`

```python
class SQLiteTimestampRepositoryContract[T: TimestampEntity](SQLiteRepositoryContract[T], TimestampRepositoryContract[T]):
    ...
```

### `SQLitePersistenceRepositoryContract`

```python
class SQLitePersistenceRepositoryContract[T: PersistenceEntity](SQLiteIdentifiedRepositoryContract[T], SQLiteTimestampRepositoryContract[T], PersistenceRepositoryContract[T]):
    ...
```
