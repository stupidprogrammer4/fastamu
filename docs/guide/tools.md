# Ready tools and explicit adapters

`papilio.tools` contains reusable capabilities. Tools do not register themselves,
choose infrastructure or depend on HTTP requests. `papilio.providers` constructs
and connects them when selected. `papilio.api.dependencies` and
`papilio.api.middlewares` adapt selected tools to HTTP.

| Capability | Reusable code | Optional integration |
| --- | --- | --- |
| Rate limiting | `tools.rate_limit` | Memory/Redis providers and HTTP adapters |
| JWT authentication | `tools.auth.JWTAuth` | `api.dependencies.auth.bearer` |
| Input/existence checks | `tools.checks.Checks`, `IDChecks` | Application services choose inheritance/composition |
| Public ID mapping | `tools.ids.IDEncryption` | `api.dependencies.ids.decode_path_id` |
| Password hashing | `security.passwords.PasswordHasher` | `providers.passwords.PasswordProvider` |

The framework does not require an identity model, JWT authentication, encoded
IDs or a rate limiter. `jwt`, `crypto` and `csrf` settings are optional, and
`CoreProvider` supplies settings only. Security primitives retain their own
explicit imports and optional installation extras.

`Checks._func_check_batch_data` matches arbitrary objects using a supplied `key`;
objects do not need an `id`. Its result contains matched items and missing-value
errors, with an empty `item_ids` set. `IDChecks` uses the same matching logic and
also fills `item_ids` from the matched rows. Both preserve first-requested order,
report each distinct missing value at its first input position, and reject a
batch with no matches.

## Choose a rate-limit backend

| Backend | Provider | Installation | Counter scope |
| --- | --- | --- | --- |
| Memory | `papilio.providers.rate_limit.memory.MemoryRateProvider` | `papilio[rate-limit]` | One backend instance in one process |
| Redis | `papilio.providers.rate_limit.redis.RedisRateProvider` plus `RedisProvider` | `papilio[rate-limit-redis]` | Shared by clients using the same Redis database/key namespace |
| Custom | `RateLimitProvider` plus a provider for `Backend` | Backend-specific | Defined by the implementation |

Memory counters are bounded by `max_size` (default 10,000). Eviction can reset a
budget; they do not enforce a shared limit across processes or restarts. Redis
borrows the existing `RedisClient` pool and does not close it separately. The
throttled-py 3.4 adapter isolates its missing public client-injection workaround
inside the Redis backend. Both ready backends use the library's sliding-window
counter implementation; there is no silent fallback from Redis to memory.
The memory adapter corrects a 3.4.1 boundary bug: a rejected first request in
a new window must not consume that window's budget. It runs under the native
atomic lock and is covered by a clock-boundary regression test. Compiled rule
objects are cached per backend with a 128-profile bound; counters stay in the store.

For a non-HTTP caller:

```python
from papilio.tools.rate_limit.backends.memory import MemoryBackend
from papilio.tools.rate_limit.config import RateLimitRule
from papilio.tools.rate_limit.limiter import RateLimiter

limiter = RateLimiter(MemoryBackend())
state = await limiter.check("export:user:42", RateLimitRule(limit=5, window_seconds=60))
```

`Backend.limit(key, rule)` atomically returns `Result(limited, state)` and raises
`Unavailable` for backend outages. `RateLimiter.check` implements the shared
rejection/outage policy. The native-library base implements common Memory/Redis
adaptation; custom backends need only the consumer contract, without inheriting
library-specific methods. SQL counter implementations are not currently shipped.

A consumed budget raises `TooManyRequestsException`. Outages fail open by default;
`closed_when_down=True` raises the same typed error with a temporary-unavailable
message. Other exceptions propagate; they are not mislabeled as an outage.

## Opt into HTTP limiting

```python
from starlette.middleware import Middleware
from papilio.api.application import create_app
from papilio.api.middlewares.rate_limit import RateLimitMiddleware
from papilio.providers.rate_limit.memory import MemoryRateProvider

settings.rate_limit.enabled = True
app = create_app(
    settings,
    providers=[MemoryRateProvider()],
    middleware=[Middleware(RateLimitMiddleware)],
)
```

This explicit middleware list replaces application defaults; include your other
middleware choices as needed. Redis wiring selects `RedisProvider(settings.redis)`
and `RedisRateProvider()` instead. Merely enabling settings never installs a
provider or middleware. The global middleware shares one IP budget across paths,
including unmatched routes. Named guards remain independently selectable through
`api.dependencies.rate_limit.rate_limit`.

`papilio providers rate-memory` and `papilio providers rate-redis` show wiring and
installation hints. For scaffolding, `--infra rate-limit` emits an explicit memory
provider and middleware. Adding `--infra redis` selects shared Redis counters in
the generated code. Installing Redis later does not change a running app's choice.

## Authentication and IDs

`bearer(authenticate)` only extracts credentials and calls the application's async
function. Its returned identity may be any application-defined type. `JWTAuth`
is an optional ready implementation, returning `Principal(subject, scopes)` and
requiring an access token. `require_access(principal_dependency, scope)` is an
optional scope policy. See [security](security.md) for wiring.

`decode_path_id` is an explicitly selected HTTP dependency. Plain `id: int` paths
continue to work. `IDEncryption` is reversible obfuscation, not encryption or
permission checking. Neither tool is activated by importing or creating an app.

## Checks, not a required service base

`services.py` was renamed to `tools/checks.py` because it contained only validation
and lookup checks. `Checks[T]` and `IDChecks[T]` do not depend on SQL models.
Declare `entity = "Product"` for error messages; generic arguments only provide
typing. Application business services remain application-owned and need not
inherit from these helpers.

## Migration

- `papilio.core.provider.CoreProvider` → `papilio.providers.base.CoreProvider`.
- `papilio.infra.{db,es,redis,http}.provider` → the corresponding module under
  `papilio.providers`. The intermediate `papilio.core.providers.*` paths also
  move to `papilio.providers.*`.
- `BaseService`/`BaseIDService` → `Checks`/`IDChecks` in `papilio.tools.checks`;
  explicitly declare the entity label.
- `papilio.security.ids` → `papilio.tools.ids`.
- `api.requests.parameters` → `api.dependencies.ids`.
- The fixed `CurrentPrincipal`/`get_current_principal` dependency was replaced by
  explicit `bearer(authenticate)`. JWT decoding no longer reads global settings.
- Rate rules/configuration live in `tools.rate_limit.config`; limiter policy and
  backend implementations live in that tool package. HTTP adapters moved to
  `api.dependencies.rate_limit` and `api.middlewares.rate_limit`.
- The previous Redis-only `RateLimitProvider()` is replaced by the selected
  `MemoryRateProvider()` or `RedisRateProvider()`; register middleware explicitly.
- Password hashing needs `PasswordProvider(salt)` or an application provider;
  it is no longer automatically supplied by `CoreProvider`.
- CSRF exception handling is optional: import `csrf_error_handler` from
  `api.responses.csrf` and explicitly register it for `CsrfProtectError` using
  `create_app(exception_handlers=...)` when installing `papilio[csrf]`.
