# Ready tools

See [usage and migration](../guide/tools.md).

## `papilio.tools.auth`

### `Principal`

```python
@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]
```

### `JWTAuth`

```python
class JWTAuth:

    def __init__(self, secret_key: str, *, algorithm: str='HS256', audience: str | None=None) -> None:
        ...

    async def authenticate(self, token: str) -> Principal:
        ...
```

## `papilio.tools.checks`

### `HasID`

```python
class HasID(Protocol):

    @property
    def id(self) -> int:
        ...
```

### `Checks`

```python
class Checks[TModel]:
    entity: str

    def _check_not_empty_dict(self, d: dict):
        ...

    def _check_not_empty_list(self, ls: list):
        ...

    def _check_for_existence(self, identifier: str, identifier_value: Any, obj: TModel | None) -> TModel:
        ...

    def _check_batch_data(self, found_ids: Sequence[int], input_ids: Sequence[int], prefix_loc: list[str]) -> Sequence[ValidationException]:
        ...

    def _func_check_batch_data(self, input_values: Sequence[Any], found_objs: Sequence[TModel], key: Callable[[TModel], Any], identifier: str, loc: list[str] | None=None) -> BatchResultType[TModel, ValidationException]:
        ...
```

### `IDChecks`

```python
class IDChecks[TIDModel: HasID](Checks[TIDModel]):

    def _check_for_id_existence(self, id: int, obj: TIDModel | None):
        ...

    def _check_batch_data(self, input_ids: Sequence[int], found_objs: Sequence[TIDModel], loc: list[str] | None=None) -> BatchResultType[TIDModel, ValidationException]:
        ...

    def _func_check_batch_data(self, input_values: Sequence[Any], found_objs: Sequence[TIDModel], key: Callable[[TIDModel], Any], identifier: str, loc: list[str] | None=None) -> BatchResultType[TIDModel, ValidationException]:
        ...
```

## `papilio.tools.ids`

### `IDEncryption`

```python
class IDEncryption:
    __slots__ = ('_mod', '_coff', '_coff_inv', '_offset')

    def __init__(self, mod: int, coff: int, offset: int=0) -> None:
        ...

    @property
    def capacity(self) -> int:
        ...

    @property
    def offset(self) -> int:
        ...

    @property
    def bounds(self) -> tuple[int, int]:
        ...

    def encode(self, id: int) -> int:
        ...

    def decode(self, public_id: int) -> int:
        ...

    def try_decode(self, public_id: int) -> int | None:
        ...

    @staticmethod
    def is_valid_coff(mod: int, coff: int) -> bool:
        ...

    def __repr__(self) -> str:
        ...
```

## `papilio.tools.rate_limit.base`

### `State`

```python
@dataclass(frozen=True, slots=True)
class State:
    limit: int
    remaining: int
    reset_after: float
    retry_after: float
```

### `Result`

```python
@dataclass(frozen=True, slots=True)
class Result:
    limited: bool
    state: State
```

### `Unavailable`

```python
class Unavailable(Exception):
    ...
```

### `Backend`

```python
class Backend(Protocol):

    async def limit(self, key: str, rule: RateLimitRule) -> Result:
        ...
```

## `papilio.tools.rate_limit.limiter`

### `RateLimiter`

```python
class RateLimiter:

    def __init__(self, backend: Backend) -> None:
        ...

    async def check(self, key: str, rule: RateLimitRule, *, closed_when_down: bool=False) -> State | None:
        ...
```

## `papilio.tools.rate_limit.backends.base`

### `ThrottledBackend`

```python
class ThrottledBackend:

    def __init__(self, store: BaseStore, *, actions: Sequence[type[BaseAtomicAction]]=()) -> None:
        ...

    def _make_limiter(self, limit: int, window: int) -> SlidingWindowRateLimiter:
        ...

    async def limit(self, key: str, rule: RateLimitRule) -> Result:
        ...
```

## `papilio.tools.rate_limit.backends.memory`

### `MemoryBackend`

```python
class MemoryBackend(ThrottledBackend):

    def __init__(self, *, max_size: int=10000) -> None:
        ...
```

## `papilio.tools.rate_limit.backends.redis`

### `RedisBackend`

```python
class RedisBackend(ThrottledBackend):

    def __init__(self, client: Redis) -> None:
        ...
```

## `papilio.providers.rate_limit.base`

### `RateLimitProvider`

```python
class RateLimitProvider(Provider):

    @provide(scope=Scope.APP)
    def limiter(self, backend: Backend) -> RateLimiter:
        ...
```

## `papilio.providers.rate_limit.memory`

### `MemoryRateProvider`

```python
class MemoryRateProvider(RateLimitProvider):

    def __init__(self, *, max_size: int=10000) -> None:
        ...

    @provide(scope=Scope.APP)
    def backend(self) -> Backend:
        ...
```

## `papilio.providers.rate_limit.redis`

### `RedisRateProvider`

```python
class RedisRateProvider(RateLimitProvider):

    @provide(scope=Scope.APP)
    def backend(self, redis: RedisClient) -> Backend:
        ...
```

## `papilio.providers.passwords`

### `PasswordProvider`

```python
class PasswordProvider(Provider):

    def __init__(self, salt: str) -> None:
        ...

    @provide(scope=Scope.APP)
    def hasher(self) -> PasswordHasher:
        ...
```
