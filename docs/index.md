# Learn Papilio

Papilio is a toolkit for building modular APIs with FastAPI and Dishka. It provides application assembly, typed database repositories, transaction boundaries, API schemas, infrastructure clients and CLI templates. You choose the infrastructure and implement your application behavior.

This guide describes **the current checkout**. The Python package and CLI are named `papilio`. Do not use the former `fastamu` or `papilio_api` import paths in new applications.

## Learning path

1. [Install Papilio and run your first application](guide/start.md). Start without a database.
2. [Build a complete CRUD feature](guide/tutorial.md), from input validation to SQL migrations and HTTP requests.
3. Learn [models](guide/models.md), [repositories and reports](guide/repositories.md), and [transaction ownership](guide/transactions.md).
4. Define [API contracts](guide/api.md), [authentication and rate limits](guide/security.md).
5. Add the infrastructure you need: [Elasticsearch](guide/cqrs.md), [HTTP and Redis](guide/clients.md), or [files, CSV and Excel](guide/files.md).
6. Add [tests](guide/testing.md) and review [operations and troubleshooting](guide/operations.md).

For date conversions, encoded identifiers, amount conversions and encryption primitives, see [supporting utilities](guide/utilities.md).

## Find the right tool

| Need | Starting point |
| --- | --- |
| Assemble an API with custom settings and routers | `create_app` |
| Generate a project or feature module | `papilio new`, `papilio module` |
| Manage dependency lifetimes | Dishka providers and scopes |
| CRUD over one SQL table | A backend-specific repository |
| Joins, aggregates and reports | A backend-specific reader and `uow.execute` |
| Commit and rollback an operation | `transaction` or `@transactional` |
| Build custom SQL | Protected backend builders and SQLAlchemy |
| Search documents | `ESRepository` |
| Call an external API or access Redis | `BaseGateway`, `RedisClient` |
| Read or write a file | The reader and writer for that format |

## Guides, examples and reference

The guides explain how the pieces connect. [Runnable examples](examples/index.md) are real source files with no external service requirements. The API reference records source signatures, including protected extension tools and backend-specific contracts. Its declaration blocks omit implementation bodies and are not standalone programs.

Use the reference for your selected database. Return values and bulk method arguments are intentionally not identical across every backend.

## Current boundaries

This package does not provide a task runtime, projection delivery, event publishing, automatic retries or an outbox. The CQRS template separates SQL commands and Elasticsearch queries; it does not synchronize those stores. Infrastructure is installed through extras and connected through explicit providers.

CLI templates are distinct from the optional `papilio.modules.ops` reference modules. Start with your own modules; adopting that reference bundle is an explicit choice.
