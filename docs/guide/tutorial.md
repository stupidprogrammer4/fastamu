# Build a complete CRUD feature

This tutorial creates a PostgreSQL product module. You need an empty development database, a separate test database and the environment from [installation](start.md). For a database example requiring no server, use the [SQLite example](../examples/index.md).

## 1. Generate the project and module

Start in the framework checkout:

```bash
python -m pip install -e '.[server,postgresql,test]'
papilio new shop --dir /tmp/papilio-learning/shop --infra postgresql
cd /tmp/papilio-learning/shop
python -m pip install -e .
papilio module product
```

Update the generated `config.yml` to point at your databases:

```yaml
db:
  dsn: postgresql+asyncpg://postgres:password@127.0.0.1:5432/shop
  test_dsn: postgresql+asyncpg://postgres:password@127.0.0.1:5432/shop_test
  pool_size: 5
  max_overflow: 5
  pool_timeout: 30
  pool_recycle: 1800
```

The CLI currently generates PostgreSQL SQL templates. Runtime support for other backends does not imply a CLI template for each one.

## 2. Define the stored entity

Replace `shop/modules/products/domain/entities.py` with:

```python
from papilio.infra.db.schema.fields import CharField, IntField
from papilio.infra.db.schema.entity import PersistenceEntity


class ProductModel(PersistenceEntity):
    sku: str = CharField(40, unique=True)
    title: str = CharField(200)
    quantity: int = IntField(default=0)
```

`PersistenceEntity` supplies the ID and timestamps. It does not include a version counter. The generated `infra/tables.py` maps this entity to a table, and the repository explicitly binds that table through its `table` attribute.

## 3. Define create and update inputs

Replace `shop/modules/products/domain/dtos.py` with:

```python
from pydantic import Field
from papilio.schemas.inputs import BaseDTO


class ProductCreate(BaseDTO):
    sku: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=0, ge=0)


class ProductUpdate(BaseDTO):
    title: str = Field(default="Untitled", min_length=1, max_length=200)
    quantity: int = Field(default=0, ge=0)
```

Update defaults allow a field to be omitted. `to_row()` uses `exclude_unset=True`, so only explicitly supplied fields become updates: an omitted title does **not** change to `"Untitled"`. Explicit `null` is invalid here. The generated service rejects an empty update dictionary.

The generated service already provides create, update, get-by-ID and remove methods. Write operations use `@transactional`; the update path does not need a preliminary SELECT.

## 4. Choose the public output

Replace `shop/modules/products/routers/schemas.py` with:

```python
from papilio.schemas.outputs import BaseOutput


class ProductOut(BaseOutput):
    id: int
    sku: str
    title: str
    quantity: int
```

The generated router uses this response model. Future internal table columns will not automatically become API fields.

## 5. Create and apply a migration

From the generated project root:

```bash
alembic revision --autogenerate -m 'create products'
alembic upgrade head
python -m uvicorn shop.main:app --reload
```

Review the migration before applying it. A column rename can be proposed as a drop and an addition. Creating the app does not run migrations automatically.

## 6. Exercise the feature

```bash
curl -X POST http://127.0.0.1:8000/products \
  -H 'Content-Type: application/json' \
  -d '{"sku":"BOOK","title":"Notebook","quantity":2}'

curl http://127.0.0.1:8000/products/1

curl -X PATCH http://127.0.0.1:8000/products/1 \
  -H 'Content-Type: application/json' \
  -d '{"quantity":5}'

curl -X DELETE http://127.0.0.1:8000/products/1
```

Use the ID returned by creation; `1` assumes an empty example database. Creation returns 201, reads and updates return an envelope, and deletion returns an integer affected-row count.

A duplicate SKU raises a database constraint error. If your API should return an application-specific 409, map that constraint error in your service; this translation is not automatic.

## 7. Understand the wiring

`app.modules` points to `shop.modules`. At startup, the bootstrapper discovers tables, providers and routers. `PGProvider` supplies an application-scoped connection and request-scoped UoW. The module provider connects the repository and service. `DishkaRoute` injects the service into each endpoint.

Next, add [custom queries and reports](repositories.md), then test [commit and rollback behavior](testing.md).
