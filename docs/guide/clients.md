# HTTP and Redis

Infrastructure clients are optional and shared through application-scoped providers. Repositories and services can receive them through explicit constructor types.

## HTTP configuration and provider

Install the `http` extra. Add to the complete settings file:

```yaml
http:
  max_connections: 100
  max_keepalive_connections: 20
  keepalive_expiry: 30
  timeout: 15
  connect_timeout: 5
  follow_redirects: true
```

Register `HTTPProvider(settings.http)` after establishing that the optional section is present. The provider yields an `HTTPConnection` and closes its HTTPX client on shutdown.

## Build a gateway for an external service

```python
from papilio.infra.http.gateway import BaseGateway
from papilio.schemas.outputs import BaseOutput


class Rate(BaseOutput):
    symbol: str
    value: float


class RatesGateway(BaseGateway):
    __base_url__ = "https://api.example.com/v1"
    default_timeout = 5.0

    async def rate(self, symbol: str) -> Rate:
        response = await self.get("rates", params={"symbol": symbol})
        response.raise_for_status()
        return Rate.model_validate(response.json())
```

The URL is illustrative, not a working service. Register the gateway with a provider factory so optional constructor values do not become unintended DI dependencies:

```python
from dishka import Provider, Scope, provide
from papilio.infra.http.connection import HTTPConnection


class RatesProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def gateway(self, connection: HTTPConnection) -> RatesGateway:
        return RatesGateway(connection)
```

`get`, `post` and `request` return `httpx.Response`. Interpret status codes and external JSON in the gateway. `url_of` joins relative paths to the base URL and preserves absolute URLs; only accept caller-controlled destinations when that is intended. Per-call headers override gateway headers. A gateway timeout overrides the connection default.

For streaming or HTTPX features outside the wrapper, use `gateway.client` and manage the response lifetime explicitly. Reuse the pool instead of constructing a new HTTPConnection for each call. No automatic retry policy is installed.

## Redis configuration and provider

Install `redis` and add:

```yaml
redis:
  url: redis://127.0.0.1:6379/0
  max_connections: 10
  socket_timeout: 5
  socket_connect_timeout: 5
  health_check_interval: 30
```

Register `RedisProvider(settings.redis)`. Example service:

```python
from papilio.infra.redis.client import RedisClient


class GreetingCache:
    def __init__(self, redis: RedisClient):
        self.redis = redis

    async def store(self, user_id: str, text: str) -> None:
        await self.redis.client.set(f"greetings:{user_id}", text, ex=60)

    async def read(self, user_id: str) -> str | None:
        return await self.redis.client.get(f"greetings:{user_id}")
```

The wrapper configures `decode_responses=True`, so ordinary text GET results are strings. `.client` exposes native Redis commands, pipelines and scripts. `ping()` is an explicit health check and `close()` closes the client; the provider owns cleanup when used through DI.

Choose namespaces, expiry, serialization and failure behavior in your own cache/queue abstraction. A Redis write is not part of a SQL transaction. There is no implicit Redis queue or projection repair policy in this package.

[Client API reference](../reference/clients.md)
