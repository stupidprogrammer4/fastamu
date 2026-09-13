# HTTP and Redis

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.http.connection`

### `HTTPConnection`

```python
class HTTPConnection:
    def __init__(self, *, max_connections: int, max_keepalive_connections: int, keepalive_expiry: float, timeout: float, connect_timeout: float, follow_redirects: bool=True) -> None:
        ...

    async def close(self) -> None:
        ...
```

## `papilio.infra.http.gateway`

```python
user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
```

### `BaseGateway`

```python
class BaseGateway:
    default_timeout: float | None = None
    def __init__(self, connection: HTTPConnection, headers: dict[str, str] | None=None, timeout: float | None=None) -> None:
        ...

    @property
    def client(self) -> httpx.AsyncClient:
        ...

    def url_of(self, path: str) -> str:
        ...

    def headers_of(self, headers: dict[str, str] | None=None) -> dict[str, str]:
        ...

    async def request(self, url: str, *, method: str | None=None, headers: dict[str, str] | None=None, params: dict[str, Any] | None=None, json: Any=None, data: dict[str, Any] | None=None) -> httpx.Response:
        ...

    async def get(self, url: str, *, headers: dict[str, str] | None=None, params: dict[str, Any] | None=None) -> httpx.Response:
        ...

    async def post(self, url: str, *, headers: dict[str, str] | None=None, params: dict[str, Any] | None=None, json: Any=None, data: dict[str, Any] | None=None) -> httpx.Response:
        ...
```

## `papilio.infra.http.provider`

### `HTTPProvider`

```python
class HTTPProvider(Provider):
    def __init__(self, config: HTTPConfig) -> None:
        ...

    @provide(scope=Scope.APP)
    async def http(self) -> AsyncIterator[HTTPConnection]:
        ...
```

## `papilio.infra.redis.client`

### `resolve`

```python
async def resolve[T](value: Awaitable[T] | T) -> T:
    ...
```

### `RedisClient`

```python
class RedisClient:
    def __init__(self, url: str, *, max_connections: int, socket_timeout: float, socket_connect_timeout: float, health_check_interval: int) -> None:
        ...

    async def ping(self) -> bool:
        ...

    async def close(self) -> None:
        ...
```

## `papilio.infra.redis.provider`

### `RedisProvider`

```python
class RedisProvider(Provider):
    def __init__(self, config: RedisConfig) -> None:
        ...

    @provide(scope=Scope.APP)
    async def redis(self) -> AsyncIterator[RedisClient]:
        ...
```
