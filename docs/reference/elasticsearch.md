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

## `papilio.infra.es.provider`

### `ESProvider`

```python
class ESProvider(Provider):
    def __init__(self, config: ESConfig) -> None:
        ...

    @provide(scope=Scope.APP)
    async def es(self) -> AsyncIterator[ESClient]:
        ...
```

## `papilio.infra.es.repository`

### `ESRepository`

```python
class ESRepository[TDoc: AsyncDocument]:
    def __init__(self, es: ESClient) -> None:
        ...

    async def init(self) -> None:
        ...

    async def save(self, doc: TDoc, **options: Any) -> TDoc:
        ...

    async def patch_by_id(self, id: str, fields: dict[str, Any]) -> None:
        ...

    async def bulk_insert(self, docs: Sequence[TDoc], *, refresh: bool=False) -> int:
        ...

    async def bulk_update(self, updates: Mapping[str, dict[str, Any]], *, refresh: bool=False) -> int:
        ...

    async def bulk_delete(self, ids: Sequence[str], *, refresh: bool=False) -> int:
        ...

    async def get(self, id: str) -> TDoc | None:
        ...

    async def update(self, doc: TDoc, **fields: Any) -> TDoc:
        ...

    async def delete(self, doc: TDoc) -> None:
        ...

    async def exists(self, id: str) -> bool:
        ...

    def search(self) -> AsyncSearch[TDoc]:
        ...
```

## `papilio.infra.es.types`

### `MetaType`

```python
class MetaType(TypedDict):
    id: int
```
