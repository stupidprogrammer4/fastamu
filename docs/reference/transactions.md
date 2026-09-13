# UnitOfWork and transactions

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.connection`

### `DBConnection`

```python
class DBConnection[U: UnitOfWork]:
    def __init__(self, dsn: str, pool_size: int, max_overflow: int, pool_timeout: int, pool_recycle: int, *, uow_factory: Callable[['DBConnection[U]'], U]) -> None:
        ...

    def uow(self) -> U:
        ...

    @property
    def dialect(self) -> Dialect:
        ...

    async def dispose(self) -> None:
        ...
```

## `papilio.infra.db.provider`

### `PostgreSQLProvider`

```python
class PostgreSQLProvider(Provider):
    def __init__(self, config: DatabaseConfig) -> None:
        ...

    @provide(scope=Scope.REQUEST)
    async def uow(self, connection: DBConnection[PostgreSQLUnitOfWork]) -> AsyncIterator[PostgreSQLUnitOfWork]:
        ...

    @provide(scope=Scope.REQUEST)
    def session(self, uow: PostgreSQLUnitOfWork) -> AsyncSession:
        ...

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncIterator[DBConnection[PostgreSQLUnitOfWork]]:
        ...
```

## `papilio.infra.db.transaction`

### `TransactionRollbackOnly`

```python
class TransactionRollbackOnly(RuntimeError):
    ...
```

### `Transaction`

```python
class Transaction:
    unit: UnitOfWork
    owner: asyncio.Task | None
    sql_transaction: AsyncSessionTransaction
    rollback_only: bool = False
    active: bool = True
    def check(self) -> None:
        ...
```

### `active_transaction`

```python
def active_transaction() -> Transaction | None:
    ...
```

### `current_transaction`

```python
def current_transaction() -> Transaction:
    ...
```

### `transaction`

```python
@asynccontextmanager
async def transaction(unit: UnitOfWork | None=None) -> AsyncGenerator[Transaction, None]:
    ...
```

## `papilio.infra.db.uow`

```python
type StatementParameters = Mapping[str, Any] | Sequence[Mapping[str, Any]]
```

### `UnitOfWork`

```python
class UnitOfWork:
    def __init__(self, connection: 'DBConnection[Self]') -> None:
        ...

    @property
    def is_open(self) -> bool:
        ...

    @property
    def session(self) -> AsyncSession:
        ...

    @property
    def in_transaction(self) -> bool:
        ...

    async def open(self) -> Self:
        ...

    async def close(self) -> None:
        ...

    async def __aenter__(self) -> Self:
        ...

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        ...

    @classmethod
    def current(cls) -> 'UnitOfWork | None':
        ...

    @contextmanager
    def activate(self) -> Generator[Self]:
        ...

    def transaction(self) -> AbstractAsyncContextManager['Transaction']:
        ...

    def savepoint(self) -> AsyncSessionTransaction:
        ...

    async def commit(self) -> None:
        ...

    async def rollback(self) -> None:
        ...

    async def flush(self) -> None:
        ...

    async def refresh(self, instance: object, *, attributes: Sequence[str] | None=None) -> None:
        ...

    @overload
    async def execute[T: tuple[Any, ...]](self, stmt: TypedReturnsRows[T], params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> Result[T]:
        ...

    @overload
    async def execute(self, stmt: Executable, params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> Result[Any]:
        ...

    async def execute(self, stmt: Executable, params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> Result[Any]:
        ...

    @overload
    async def stream[T: tuple[Any, ...]](self, stmt: TypedReturnsRows[T], params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> AsyncResult[T]:
        ...

    @overload
    async def stream(self, stmt: Executable, params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> AsyncResult[Any]:
        ...

    async def stream(self, stmt: Executable, params: StatementParameters | None=None, *, execution_options: Mapping[str, Any]=MappingProxyType({}), bind_arguments: dict[str, Any] | None=None) -> AsyncResult[Any]:
        ...

    async def now(self) -> datetime:
        ...
```

### `PostgreSQLUnitOfWork`

```python
class PostgreSQLUnitOfWork(UnitOfWork):
    ...
```

### `MySQLUnitOfWork`

```python
class MySQLUnitOfWork(UnitOfWork):
    ...
```

### `MariaDBUnitOfWork`

```python
class MariaDBUnitOfWork(UnitOfWork):
    ...
```

### `SQLiteUnitOfWork`

```python
class SQLiteUnitOfWork(UnitOfWork):
    ...
```

### `OracleUnitOfWork`

```python
class OracleUnitOfWork(UnitOfWork):
    ...
```

### `MSSQLUnitOfWork`

```python
class MSSQLUnitOfWork(UnitOfWork):
    ...
```
