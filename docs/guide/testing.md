# Testing and database migrations

Test application behavior through public boundaries, and test backend-specific SQL against the selected database. SQLite tests do not establish PostgreSQL, MySQL or Oracle compatibility.

## Test an app without infrastructure

Install `test`. This test imports the runnable application by adding `docs/examples` to the import path, and uses a fresh app:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from plain_app import build_app


@pytest.mark.asyncio
async def test_greeting():
    app = build_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/greetings", json={"name": "Sara"})
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {"text": "Hello, Sara!"},
    }
```

HTTPX's ASGI transport does not run lifespan for you. The explicit context initializes resources and closes the container afterward. Avoid reusing an app whose container has already been closed.

## Generated project tests

The project template creates an `anonymous` fixture that builds a fresh app, disables rate limiting, switches SQL to `db.test_dsn`, enters lifespan and yields an HTTP client. It does not automatically create the database or migrate it.

For the product tutorial, apply migrations to the separate test database before testing. Run this from the generated project root in a standalone process:

```python
from alembic import command
from alembic.config import Config
from papilio.core.config import get_settings

settings = get_settings()
assert settings.db is not None
config = Config("alembic.ini")
config.set_main_option("sqlalchemy.url", settings.db.test_dsn.replace("%", "%%"))
command.upgrade(config, "head")
```

Then add a feature test:

```python
from uuid import uuid4


async def test_product_roundtrip(anonymous):
    response = await anonymous.post(
        "/products",
        json={"sku": uuid4().hex, "title": "Notebook", "quantity": 2},
    )
    assert response.status_code == 201
    product_id = response.json()["data"]["id"]
    try:
        response = await anonymous.patch(
            f"/products/{product_id}", json={"quantity": 5}
        )
        assert response.status_code == 200
        response = await anonymous.get(f"/products/{product_id}")
        assert response.json()["data"]["quantity"] == 5
    finally:
        await anonymous.delete(f"/products/{product_id}")
```

Run `python -m pytest` from the generated root. This checks separate requests and persistence after commit. Also test invalid input, missing entities, database constraints and rollback after a failed multi-write operation.

## Framework test helpers

`papilio.testing.plugin` is the lightweight automatically loaded pytest plugin. It adds markers based on test folders. `papilio.testing.fixtures` is a separate opt-in infrastructure harness for application-owned modules; importing it is not required for a plain project. Install `test`, `postgresql`, `es`, `redis`, `http`, `rate-limit` and `passwords` to use that harness. Its database preparation can modify a test database, so read its configuration before adopting it.

## Maintain migrations

Use `alembic revision --autogenerate` to propose schema changes, review the revision, then `alembic upgrade head`. The generated migration environment imports configured module tables and uses SQLModel metadata. Explicit Alembic URL overrides take precedence over the application's normal DSN.

Check both migration-from-empty and upgrade-from-previous-schema paths. Index creation, column renames and data backfills deserve separate review. Application startup is not migration management.

## Test the documentation examples

From the framework checkout:

```bash
python docs/examples/sqlite_repository.py
python docs/examples/file_pipeline.py
python docs/examples/excel_roundtrip.py
python -m mkdocs build --strict
```

These commands need the `docs`, `sqlite`, `files`, `csv` and `excel` extras. The examples check SQLite persistence, file/CSV processing and Excel roundtrips without external services. Use the HTTP test above with the `test` extra. Update reference signatures alongside API changes and build the site in strict mode to catch broken documentation links.
