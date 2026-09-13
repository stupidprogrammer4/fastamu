# Transactions and UnitOfWork

A connection owns the engine and pool. A UnitOfWork owns one session. A transaction context owns the commit/rollback boundary. Closing a UoW never commits implicitly.

## Open a unit and own a transaction

Given an existing connection, repository and valid input:

```python
from papilio.infra.db.transaction import transaction

async with connection.uow() as uow:
    repo = ProductRepository(uow)
    async with transaction(uow):
        product = await repo.create(data)
```

The inner context commits on success. On failure it rolls back and propagates the exception. The outer context closes the session. Repositories do not commit themselves. See the [SQLite example](../examples/index.md) for complete connection setup and disposal.

## Use a decorator in a service

```python
from papilio.infra.db.tools.decorators import transactional


class StockService:
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    @transactional
    async def change(self, id: int, quantity: int):
        return await self.repo.update_by_id(id, {"quantity": quantity})
```

The decorator requires an open, active UoW, supplied by the request provider or a manual UoW context. Function inspection happens when the decorator is applied. Outside HTTP, enter `async with connection.uow()` before calling the service.

## Nested operations

Nested transactional services join the outer operation. They do not commit independently. If an inner operation fails, the transaction becomes rollback-only. Even when its caller catches the error, the outer boundary raises `TransactionRollbackOnly` instead of committing partial work.

A savepoint is the separate tool for an isolated SQL failure:

```python
from sqlalchemy.exc import IntegrityError

async with transaction(uow):
    try:
        async with uow.savepoint():
            await repo.create(optional_record)
    except IntegrityError:
        pass
    await repo.create(required_record)
```

Here both records are valid application inputs. Catch the SQL exception outside the savepoint scope. Entering a savepoint flushes pending ORM changes. Do not enter another `transaction()` or `@transactional` operation inside a savepoint.

## Available UoW tools

| Tool | Responsibility |
| --- | --- |
| `execute(stmt, params, execution_options=...)` | Return SQLAlchemy's buffered result |
| `stream(stmt, ...)` | Return an open cursor, which the caller closes |
| `flush()` | Send pending ORM changes without committing |
| `refresh(instance, attributes=...)` | Explicitly read an ORM object again |
| `commit()`, `rollback()` | Fully manual boundary management |
| `savepoint()` | Nested SQL transaction |
| `now()` | SELECT the database timestamp |
| `activate()`, `current()` | Select and access the contextual unit |

The option name is `execution_options`, not `execute_options`. It passes SQLAlchemy execution options through. Do not manually commit or roll back inside a managed transaction. `refresh()` and `now()` execute real reads.

## Concurrency and multiple databases

Each concurrent task needs its own UoW. Do not share one session across branches of `asyncio.gather`. Repositories participating in one sequential operation can share a UoW.

Use explicitly typed connections and providers for different databases. You cannot switch the active unit inside an application transaction. This tool is not a distributed transaction: a SQL commit does not atomically include a Redis write or Elasticsearch request.

[Connection, UoW and transaction reference](../reference/transactions.md)
