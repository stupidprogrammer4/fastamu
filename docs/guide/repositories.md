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

The `contracts` package defines abstract obligations; `backends` contains native implementations and protected SQL builders. The executable classes in [`repositories/base.py`](../reference/repository-base.md) implement common reads, paging and timestamp filters. Backend classes inherit these implementations and satisfy their own write contracts. Common contracts require no insert, update, delete or protected native write builder. Select the base, identified, timestamp or persistence shape according to the fields your entity actually owns. A reader has only an execution context and does not require an entity type or `table`.

### Connect another backend to Dishka

Ready providers for all six backends live in `papilio.providers.db`:
`PGProvider`, `MySQLProvider`, `MariaDBProvider`, `SQLiteProvider`, `OracleProvider`
and `MSSQLProvider`. Select the matching provider and repository explicitly.

```python
from papilio.api.application import create_app
from papilio.providers.db import SQLiteProvider

app = create_app(settings, providers=[SQLiteProvider(settings.db)])
```

Configure a SQLite DSN and install `papilio[sqlite]` for this example. Register
your repository/service in the module provider. Run `papilio providers` to see
installation availability, or `papilio providers sqlite` for the import and
wiring suggestion. See [ready providers](providers.md) for custom providers,
multiple databases and optional infrastructure startup.

## Understand backend return values

| Backend | Create one | Update by ID | Delete by ID | Public upsert |
| --- | --- | --- | --- | --- |
| PostgreSQL | Model through RETURNING | Model or `None` | Model or `None` | Model / sequence of models |
| SQLite | Model through RETURNING | Model or `None` | Model or `None` | Model / sequence of models |
| MariaDB | Model through RETURNING | Affected-row count | Model or `None` | Model / sequence of models |
| MySQL | Model through flush and refresh | Affected-row count | Affected-row count | Affected-row count |
| SQL Server | Model from statement output | Model or `None` | Model or `None` | Not exposed |
| Oracle | Model from statement output | Model or `None` | Model or `None` | Not exposed |

This describes the **current implementation**, not compatibility with every historical server version. RETURNING and bulk SQL forms depend on the server and driver. Run integration tests against your deployment versions.

`rowcount` is a driver report. Especially for MySQL upsert, it is not necessarily the input count or unique entity count. Do not use it to reconstruct IDs. MySQL's batch API is `bulk_insert(data, *, insert_columns) -> int`; it executes a native INSERT without refreshing models. MySQL `bulk_create` has been removed. Migrate its callers to explicit insertion columns and a count result, adding an application read only when saved models are needed. The other five backends retain model-returning `bulk_create` in their own contracts.

`remove_by_ids(ids)` returns the deleted models on the five returning backends;
MySQL returns a count. PostgreSQL `remove(where)` also returns a sequence of
deleted models. These replace the old shared count contract. All deletes use
one native write statement without SELECT or implicit commit. An empty/missing
batch produces `[]` or MySQL's `0`; returned rows have no input-order guarantee.
Returning deletes use SQLAlchemy session synchronization from the returned
keys, so pending cached values cannot replace deleted-row values.
Returned model values describe deleted rows; they do not imply that those rows
remain stored. The generated HTTP service keeps its `0`/`1` delete response by
converting PostgreSQL's optional returned model explicitly.

MariaDB supports [INSERT/DELETE RETURNING](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#insert-delete-returning),
while its SQLAlchemy UPDATE path returns a count. Evaluate support per operation,
not per database name alone.

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
