# Changelog

## 0.3.1

- Preserve Python defaults, nullable values and database-generated values in
  field factories; string and enum server defaults accept bare literals.
- Preserve first-seen batch input order and report the original input and
  position for every missing item in linear time.
- Add read-free Elasticsearch patch and bulk-delete operations, and serialize
  full documents without dropping false or null values.
- Add optional JWT audience validation.
- Accept any Pydantic response payload and metadata, omit empty envelope fields
  and normalize validation context for JSON output.
- Run registered post-commit callbacks in `DBUnitOfWork` and discard them on
  rollback while retaining guaranteed session cleanup.

## 0.3.0

This release changes public import paths and configuration. Migrate consumers
before upgrading from 0.2.x; old paths are not compatibility aliases.

### Changes

- Split common models, schemas, security, types and projection contracts into
  dedicated packages. Schema responses use `outputs` modules.
- Replace `infra.postgres` with `infra.db`: shared repositories, connections and
  units of work, with SQL dialect adapters. Table names now split CamelCase before
  pluralizing the final word (`ProductVariantTable` -> `tbl_product_variants`).
- Separate optional events (FastStream), projections (Taskiq/RabbitMQ) and
  schedulers (Taskiq/Redis) under `fastamu.tasks`.
- Share one projection broker across domain queues. Each queue uses prefetch=1
  and a single active consumer. Multiple projection operations can share a queue.
  Failed deliveries retry in place with fresh Dishka scopes and a configured
  delay; an exhausted delivery pauses its queue until repair and worker restart.
- Add task discovery and CLI scaffolding for subscribers, publishers, schedulers
  and optional CQRS, plus the dedicated projection worker command.
- Replace the custom infra rate-limit wrapper/result classes with direct
  `throttled-py` objects in `fastamu.web.ratelimit`. Reuse the app's Redis pool.
  Independent HTTP quota checks run concurrently and finish before rejection.

### Consumer migration

- Change `postgresql` configuration to `db` and `PG*` repository/connection/UoW
  imports to the corresponding `DB*` classes in `fastamu.infra.db`.
- Update `common.bases` imports to `common.models`, `common.schemas`,
  `common.services` or `common.projections`; move security helpers to
  `common.security`, enums/constants/aliases to `common.types`.
- Move PostgreSQL-only `ArrayField` and `JSONBField` imports to
  `fastamu.infra.db.dialects.postgresql`. Use `JSONField` for portable JSON.
- Inspect generated Alembic changes for renamed multiword tables. Existing
  tables require an explicit rename migration, not drop-and-create.
- Configure only the task features needed under `tasks.events`,
  `tasks.projection`, and `tasks.schedulers`; omitted/null sections are disabled.
  Install matching extras: `fastamu[events,cqrs,scheduler]`.
- Replace old event/projection decorators with native FastStream routers and
  the new projection contracts. Publish projection work after the source commit.
- Import HTTP guards from `fastamu.web.ratelimit`. Custom FastAPI applications
  must add `RateLimitProvider()` to their Dishka container.

### Limits and validation

- Live repository checks cover PostgreSQL, MySQL and SQLite. MSSQL and Oracle
  receive SQL compilation checks, not live-server validation; their atomic
  upsert operation is explicitly unsupported. MariaDB has an adapter but has not
  been tested against a live server for this release.
- Projection ordering applies to delivery order within a queue, not database
  commit order across publishers. Delivery is at least once; handlers must be
  safe to retry. Source commits and message publication are not atomic.
- Sharing Redis with `throttled-py` currently uses one isolated private-backend
  assignment, covered by a compatibility test. Recheck it on dependency upgrades.
- The test suite includes real RabbitMQ ordering/retry checks, database CRUD,
  HTTP guard and rate-limit tests. Package build, lint and Pyright are checked
  before tagging. A dependency emits a Python generator `throw()` deprecation
  warning during Taskiq/Dishka retry tests.
