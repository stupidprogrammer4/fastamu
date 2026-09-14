# Repositories, custom SQL and reporting

A repository binds one table. A reader has no table requirement and is suitable for joins and reports. Both receive the UoW for their selected database. Build a statement locally, then execute it through the UoW.

## Select the backend explicitly

```python
from papilio.infra.db.repositories.backends.postgresql import (
    PGIdentifiedRepository,
)
from shop.modules.products.domain.entities import ProductModel
from shop.modules.products.infra.tables import ProductTable


class ProductRepository(PGIdentifiedRepository[ProductModel]):
    table = ProductTable
```

This repository requires `PGUnitOfWork`. There is no per-request repository routing based on the DSN. For SQLite, select both a SQLite repository and SQLite UoW; the [complete example](../examples/index.md) demonstrates this.

The `contracts` package defines abstract obligations; `backends` contains usable implementations and protected SQL builders. Select the base, identified, timestamp or persistence shape according to the fields your entity actually owns. A reader has only an execution context and does not require an entity type or `table`.

### Connect another backend to Dishka

The bundled SQL provider is `PGProvider`. For another backend, write an ordinary typed provider; no provider factory or runtime backend validator is required. For example, a SQLite application can use:

```python
from collections.abc import AsyncIterator
from dishka import Provider, Scope, provide
from papilio.core.config import DatabaseConfig
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import SQLiteUnitOfWork


class SQLiteProvider(Provider):
    def __init__(self, config: DatabaseConfig):
        super().__init__()
        self.config = config

    @provide(scope=Scope.APP)
    async def connection(self) -> AsyncIterator[DBConnection[SQLiteUnitOfWork]]:
        connection = DBConnection(
            dsn=self.config.dsn,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_recycle=self.config.pool_recycle,
            uow_factory=SQLiteUnitOfWork,
        )
        try:
            yield connection
        finally:
            await connection.dispose()

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[SQLiteUnitOfWork]
    ) -> AsyncIterator[SQLiteUnitOfWork]:
        async with connection.uow() as unit:
            yield unit
```

Pass `SQLiteProvider(settings.db)` to `create_app` after configuring a SQLite DSN and installing `sqlite`. Register your SQLite repository and service in the module provider. For another database, use its corresponding UoW, repository classes, driver and DSN together.

## Understand backend return values

| Backend | Create one | Update by ID | Public upsert |
| --- | --- | --- | --- |
| PostgreSQL | Model through RETURNING | Model or `None` | Model / sequence of models |
| SQLite | Model through RETURNING | Model or `None` | Model / sequence of models |
| MariaDB | Model through RETURNING | Affected-row count | Model / sequence of models |
| MySQL | Model through flush and refresh | Affected-row count | Affected-row count |
| SQL Server | Model from statement output | Model or `None` | Not exposed |
| Oracle | Model from statement output | Model or `None` | Not exposed |

This describes the **current implementation**, not compatibility with every historical server version. RETURNING and bulk SQL forms depend on the server and driver. Run integration tests against your deployment versions.

`rowcount` is a driver report. Especially for MySQL upsert, it is not necessarily the input count or unique entity count. Do not use it to reconstruct IDs. MySQL `bulk_create` refreshes every returned model; use its separate `bulk_insert` tool when only an affected-row count is needed.

## Read and paginate

On an identified repository:

```python
product = await repo.get_by_id(42)
products = await repo.get_by_ids([42, 43])
page = await repo.get_paged(limit=20, offset=40)
```

`PagedType` contains `items` and `total_items`. Do not assume that `get_by_ids` preserves input order. PostgreSQL additionally offers `get_one`, filtered `get_all`, `exists`, `count` and `get_page(order_by=...)`; do not assume those signatures on all backends.

For a custom single-model query:

```python
from sqlalchemy import select
from papilio.infra.db.tools.read import fetch_page

stmt = select(ProductTable).where(ProductTable.quantity > 0)
stmt = stmt.order_by(ProductTable.id)
page = await fetch_page(uow, stmt, limit=20, offset=0)
```

`fetch_page` executes two SELECTs: count and page data. Empty pages still include the total. Under common isolation settings the two statements need not observe the same concurrent snapshot. Always choose a stable order. Large offsets and expensive counts still have costs; when a total is unnecessary, build a limited query or keyset pagination using SQLAlchemy.

## Read aggregates and join multiple tables

Using the table from the tutorial:

```python
from sqlalchemy import func, select
from papilio.infra.db.repositories.backends.postgresql import PGReader
from shop.modules.products.infra.tables import ProductTable


class StockReader(PGReader):
    async def totals(self):
        stmt = select(
            func.count(ProductTable.id).label("products"),
            func.coalesce(func.sum(ProductTable.quantity), 0).label("units"),
        )
        result = await self.uow.execute(stmt)
        return dict(result.mappings().one())
```

For multiple tables, select their columns and use `.join(OtherTable, condition)`. Label colliding names. `scalars()` returns only the first selected value; use `mappings()` or result rows for multi-column reports. `fetch_page` is a scalar/model helper, not a general report serializer.

## Upsert tools

Add this PostgreSQL-specific method to the product repository:

```python
async def store_stock(self, data: ProductModel) -> ProductModel:
    columns = self.table.__table__.c
    stmt = self._upsert_stmt(
        data.to_row(),
        conflict_columns=[columns.sku],
        update_columns=[columns.quantity],
    )
    stmt = stmt.returning(self.table).execution_options(populate_existing=True)
    result = await self.uow.execute(stmt)
    return result.scalar_one()
```

The protected builder constructs SQL without executing or committing. The ready-made `upsert` accepts the same column selection. Bulk has its own builder and public operation:

```python
columns = ProductTable.__table__.c
stored = await repo.bulk_upsert(
    [
        ProductModel(sku="A", title="First", quantity=2),
        ProductModel(sku="B", title="Second", quantity=3),
    ],
    insert_columns={
        "sku": columns.sku,
        "title": columns.title,
        "quantity": columns.quantity,
    },
    conflict_columns=[columns.sku],
    update_columns=[columns.quantity],
)
```

`insert_columns` maps input field names to SQL columns. The conflict target must match a suitable unique constraint. `changes` supplies custom SQL assignments alongside selected update columns. MySQL and MariaDB do not accept `conflict_columns`: the server determines collisions from its unique keys.

## Bulk update with explicit columns

PostgreSQL accepts row mappings and match columns, including composite keys:

```python
columns = ProductTable.__table__.c
updated = await repo.bulk_update(
    [{"sku": "A", "quantity": 8}, {"sku": "B", "quantity": 9}],
    key_columns=[columns.sku],
    update_columns=[columns.quantity],
)
```

Other backends have an ID-based bulk signature. For example, with a SQLite repository bound to this entity:

```python
updated = await sqlite_repo.bulk_update(
    [ProductModel.patch(id=1, quantity=8)],
    update_columns={"quantity": ProductTable.__table__.c.quantity},
)
```

Provide a nonempty batch, required fields and unique match keys at the application boundary. The repository does not repair incomplete rows or discover update columns. For large batches, choose a caller-side chunk size compatible with server parameter limits.

## Stream results

```python
from contextlib import aclosing
from sqlalchemy import select
from papilio.infra.db.tools.read import stream

stmt = select(ProductTable).order_by(ProductTable.id)
async with aclosing(stream(uow, stmt, batch_size=500)) as products:
    async for product in products:
        await consume(product)
```

`consume` is your async consumer. Keep the UoW open for the entire iteration. `aclosing` closes the cursor even after an early break. Collecting the stream into a list loses its memory advantage.

## Backend references

[PostgreSQL](../reference/postgresql.md) · [MySQL](../reference/mysql.md) · [MariaDB](../reference/mariadb.md) · [SQLite](../reference/sqlite.md) · [SQL Server](../reference/mssql.md) · [Oracle](../reference/oracle.md)
