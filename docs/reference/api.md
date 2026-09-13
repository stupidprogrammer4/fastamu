# API tools

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.api.authentication`

```python
bearer = HTTPBearer(auto_error=False)
```

```python
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
```

### `Principal`

```python
class Principal:
    def __init__(self, subject: str, scopes: frozenset[str]) -> None:
        ...
```

### `get_current_principal`

```python
@inject
async def get_current_principal(credentials: Credentials, settings: FromDishka[Settings]) -> Principal:
    ...
```

```python
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
```

### `require_access`

```python
def require_access(scope: str):
    ...
```

## `papilio.api.middlewares.logging`

### `LoggingMiddleware`

```python
class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str='X-Request-ID') -> None:
        ...

    async def dispatch(self, request: Request, call_next) -> Response:
        ...
```

## `papilio.api.rate_limit.dependencies`

```python
KeyPart = Callable[[Request], Awaitable[str]]
```

```python
type NamedLimits = dict[str, Throttled]
```

### `by_ip`

```python
async def by_ip(request: Request) -> str:
    ...
```

### `by_body_field`

```python
def by_body_field(field: str) -> KeyPart:
    ...
```

### `rate_limit`

```python
def rate_limit(name: str, parts: Sequence[KeyPart]=(by_ip,), *, closed_when_down: bool=False) -> Depends:
    ...
```

## `papilio.api.rate_limit.middleware`

### `RateLimitMiddleware`

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ...
```

## `papilio.api.rate_limit.provider`

### `RateLimitProvider`

```python
class RateLimitProvider(Provider):
    scope = Scope.APP
    @provide
    def store(self, redis: RedisClient) -> RedisStore:
        ...

    @provide
    def general(self, settings: Settings, store: RedisStore) -> Throttled:
        ...

    @provide
    def rules(self, settings: Settings, store: RedisStore) -> NamedLimits:
        ...
```

## `papilio.api.requests.parameters`

### `decode_path_id`

```python
def decode_path_id(encryption: IDEncryption, entity: str, param: str='id') -> Callable[..., int]:
    ...
```

## `papilio.api.requests.queries`

### `pairs_read`

```python
def pairs_read(value: Sequence[str]) -> list[str]:
    ...
```

### `pairs_folded`

```python
def pairs_folded(value: Sequence[str]) -> dict[int, list[int]]:
    ...
```

### `BaseQuery`

```python
class BaseQuery(BaseDTO):
    model_config = ConfigDict(populate_by_name=True)
    @staticmethod
    def _carried(annotation: Any) -> Any:
        ...

    def folded(self, name: str) -> dict[int, list[int]]:
        ...
```

## `papilio.api.responses.envelope`

```python
ErrorType = Union[*errors_types,]
```

### `APIResponse`

```python
class APIResponse[TOut: BaseModel | None, TMeta: BaseModel | None](BaseModel):
    success: bool
    message_code: Optional[str] = None
    data: Optional[Union[TOut, Sequence[TOut]]] = None
    meta: Optional[TMeta] = None
    error: Optional[ErrorType] = None
    errors: Optional[Sequence[ErrorType]] = None
    @model_serializer(mode='wrap')
    def _omit_empty_envelope(self, handler: SerializerFunctionWrapHandler) -> Any:
        ...

    @classmethod
    def from_data(cls, data: Union[TOut, Sequence[TOut]], message_code: Optional[str]=None, errors: Optional[Sequence[APPException]]=None):
        ...

    @classmethod
    def from_external_error(cls, error: APPException):
        ...

    @classmethod
    def from_pydantic_error(cls, error: PydanticError):
        ...

    @staticmethod
    def _readable_context(context: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        ...

    @classmethod
    def get_server_error(cls):
        ...
```

## `papilio.api.responses.handlers`

### `external_error_handler`

```python
async def external_error_handler(request: Request, exc: APPException) -> JSONResponse:
    ...
```

### `pydantic_error_handler`

```python
async def pydantic_error_handler(request: Request, exc: PydanticError) -> JSONResponse:
    ...
```

### `http_error_handler`

```python
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    ...
```

### `csrf_error_handler`

```python
async def csrf_error_handler(request: Request, exc: CsrfProtectError) -> JSONResponse:
    ...
```

### `unexcepted_error_handler`

```python
def unexcepted_error_handler(request: Request, exc: Exception) -> JSONResponse:
    ...
```

```python
exception_handlers = {PydanticError: pydantic_error_handler, StarletteHTTPException: http_error_handler, APPException: external_error_handler, CsrfProtectError: csrf_error_handler, Exception: unexcepted_error_handler}
```

### `setup_exception_handlers`

```python
def setup_exception_handlers(app: FastAPI) -> None:
    ...
```

## `papilio.api.responses.meta`

### `PagerMeta`

```python
class PagerMeta(BaseModel):
    total_items: int
    total_pages: int
    has_prev: bool
    has_next: bool
    @classmethod
    def from_total(cls, page: int, per_page: int, total: int) -> Self:
        ...
```

### `SortMeta`

```python
class SortMeta(BaseModel):
    options: list[EnumOut]
    orders: list[EnumOut]
    @classmethod
    def of(cls, options: type[FaStrEnum]) -> 'SortMeta':
        ...
```

### `FilterMeta`

```python
class FilterMeta[TOut: BaseModel](BaseModel):
    id: int | None = None
    type: FilterType
    title: str | None = None
    options: list[TOut]
```

### `BaseMeta`

```python
class BaseMeta(BaseModel):
    pager: PagerMeta | None = None
    filters: dict[str, FilterMeta] | None = None
    sorts: SortMeta | None = None
```
