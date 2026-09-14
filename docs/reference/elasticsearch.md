# Elasticsearch

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.es.analyzers`

```python
persian_analyzer = analyzer('persian', char_filter=[_persian_zwnj], tokenizer='standard', filter=['lowercase', 'decimal_digit', 'arabic_normalization', 'persian_normalization', _persian_stop])
```

## `papilio.infra.es.client`

### `ESClient`

```python
class ESClient:
    def __init__(self, hosts: list[str], *, username: str | None=None, password: str | None=None, api_key: str | None=None, verify_certs: bool=True, ca_certs: str | None=None) -> None:
        ...

    async def close(self) -> None:
        ...
```

## `papilio.providers.es`

### `ESProvider`

```python
class ESProvider(Provider):
    def __init__(self, config: ESConfig) -> None:
        ...

    @provide(scope=Scope.APP)
    async def es(self) -> AsyncIterator[ESClient]:
        ...
```

## `papilio.infra.es.store`

`ESStore` binds an explicit document class to an ESClient. Native DSL objects
retain their complete APIs. See the [capability map and migration guide](../guide/cqrs.md#dsl-capability-map).

`Items[T]` means `Iterable[T] | AsyncIterable[T]`; `Action` is a native action
dictionary; `VersionType` is `Literal["external", "external_gte"]`.

```python
class ESStore[TDoc: AsyncDocument]:
    document: type[TDoc]

    def __init__(self, es: ESClient) -> None:
        ...

    def index(self) -> AsyncIndex:
        ...

    async def init(self, *, index: str | None=None) -> None:
        ...

    def search(self, *, index: str | None=None) -> AsyncSearch[TDoc]:
        ...

    def msearch(self) -> AsyncMultiSearch[TDoc]:
        ...

    def update_by_query(self) -> AsyncUpdateByQuery:
        ...

    async def esql(self, query: str, **options: Any) -> ObjectApiResponse[Any]:
        ...

    async def get(self, id: str, **options: Any) -> TDoc | None:
        ...

    async def mget(self, docs: Iterable[str | Action], *, missing: Literal['none', 'skip', 'raise']='none', **options: Any) -> list[TDoc | None]:
        ...

    async def exists(self, id: str, **options: Any) -> bool:
        ...

    async def save(self, doc: TDoc, *, skip_empty: bool=False, **options: Any) -> TDoc:
        ...

    async def save_version(self, doc: TDoc, version: int, *, version_type: VersionType, **options: Any) -> TDoc:
        ...

    async def create(self, doc: TDoc, **options: Any) -> TDoc:
        ...

    async def update(self, doc: TDoc, **fields: Any) -> TDoc:
        ...

    async def patch(self, id: str, fields: Mapping[str, Any] | None=None, **options: Any) -> ObjectApiResponse[Any]:
        ...

    async def delete(self, doc: TDoc, **options: Any) -> None:
        ...

    async def bulk(self, actions: Items[TDoc | Action], *, validate: bool=True, skip_empty: bool=False, **options: Any) -> tuple[int, int]:
        ...

    def stream(self, actions: Items[TDoc | Action], *, validate: bool=True, skip_empty: bool=False, **options: Any) -> AsyncIterable[tuple[bool, Action]]:
        ...

    async def bulk_index(self, docs: Items[TDoc], **options: Any) -> int:
        ...

    async def bulk_create(self, docs: Items[TDoc], **options: Any) -> int:
        ...

    async def bulk_update(self, updates: Mapping[str, dict[str, Any]], **options: Any) -> int:
        ...

    async def bulk_delete(self, ids: Items[str], **options: Any) -> int:
        ...
```

## `papilio.infra.es.types`

### `MetaType`

```python
class MetaType(TypedDict):
    id: int
```
