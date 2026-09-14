# Choose ready providers

Ready providers live in `papilio.providers`. Applications select and pass
them to `create_app`; installing extras or filling in configuration does not
register optional infrastructure. The package initializer imports no optional
clients or database drivers. Your own Dishka providers can be used instead of,
or alongside, the ready providers.

Inspect the current installation and get an import/usage suggestion:

```bash
papilio providers
papilio providers sqlite
papilio providers mysql
```

The catalog reports installed distributions for the drivers supplied by each
extra, plus install commands for missing dependencies. It does not import the
optional libraries, connect to services, install packages, or select providers
for you. Presence is not a version-compatibility or connectivity check.

| Module under `papilio.providers` | Ready classes | Configuration |
| --- | --- | --- |
| `db` | `PGProvider`, `MySQLProvider`, `MariaDBProvider`, `SQLiteProvider`, `OracleProvider`, `MSSQLProvider` | `DatabaseConfig` |
| `es` | `ESProvider` | `ESConfig` |
| `redis` | `RedisProvider` | `RedisConfig` |
| `http` | `HTTPProvider` | `HTTPConfig` |
| `rate_limit.memory` | `MemoryRateProvider` | Optional `max_size` |
| `rate_limit.redis` | `RedisRateProvider` | Injected `RedisClient` |
| `passwords` | `PasswordProvider` | Explicit salt/pepper |
| `base` | `CoreProvider` | Registered by `create_app` for settings |

For example, with the `sqlite` and `http` extras installed and their settings
configured:

```python
from papilio.api.application import create_app
from papilio.providers.db import SQLiteProvider
from papilio.providers.http import HTTPProvider

app = create_app(settings, providers=[
    SQLiteProvider(settings.db),
    HTTPProvider(settings.http),
    ProductsProvider(),  # Your application's repositories and services.
])
```

Each DB provider registers `DBConnection[BackendUnitOfWork]` at APP scope and
the exact backend UoW plus its `AsyncSession` at REQUEST scope. Connections are
created on first resolution and disposed when the container closes. UoWs close
on request exit, including errors and cancellation; they never commit implicitly.
The shared `DBProvider` implements connection lifetime. Its subclasses explicitly
declare typed Dishka registrations. Choose the matching repository, UoW, driver
and DSN; the provider does not infer a different backend from the URL.

For several databases, use Dishka components, for example
`SQLiteProvider(main_config).to_component("main")` and
`SQLiteProvider(report_config).to_component("reports")`. Register consumers in
the corresponding components. This also separates their `AsyncSession` bindings.

ES, Redis and HTTP providers lazily create one client per APP scope and close it
once. Select `MemoryRateProvider()` for local counters, or combine
`RedisProvider(settings.redis)` and `RedisRateProvider()` for shared counters.
HTTP middleware and dependencies must also be selected explicitly; see
[ready tools](tools.md).

## Choose startup work explicitly

`ESProvider` manages a client; it does not create indexes. If your application
wants discovery-based index initialization on startup, use its lifespan:

```python
from contextlib import asynccontextmanager
from papilio.core.bootstrap import Bootstrapper
from papilio.providers.es import ESProvider
from papilio.infra.es.client import ESClient

@asynccontextmanager
async def lifespan(app):
    es = await app.state.dishka_container.get(ESClient)
    await Bootstrapper(settings.app.modules).boot_es_indices(es.client)
    yield

app = create_app(settings, providers=[ESProvider(settings.es)], lifespan=lifespan)
```

The container closes even if startup fails. Existing index initialization logs
and skips individual index failures; it is not a readiness check. You may omit
this hook or replace it with application-specific setup.

`papilio new --infra es` and `--cqrs` generate this explicit lifespan. Selecting
`--infra rate-limit` writes a memory provider and middleware; also selecting
`--infra redis` chooses Redis counters.
The project/module SQL templates still target PostgreSQL; the six ready DB
providers can all be used in application-owned wiring independently of those
templates.

## Import migration

Providers now live directly under `papilio.providers`, including `base`, `db`,
`es`, `redis`, `http`, and optional tool providers. `CoreProvider` supplies only
settings. Refer to the [complete migration list](tools.md#migration) for tools,
rate limiting, authentication and password hashing.
