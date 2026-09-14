# Shared repository base

These executable classes implement common SQL operations. Each backend inherits
the appropriate entity shape and adds its native write contract and builders.
`T` is the entity type; `U` is the UnitOfWork type. Backend constructors name
that UoW explicitly for dependency injection.

`Repository` provides reads and streaming. `IdentifiedRepository` adds ID reads
and paging. `TimestampRepository` adds time filters;
`PersistenceRepository` combines both and orders by `created_at`, then `id`.
`Reader` only stores the execution context for application-defined queries.
There are no insert, update, delete or upsert obligations in this base, including
protected native builders. PostgreSQL retains its filtered read overrides.

Code blocks show signatures; `...` replaces implementation bodies. See
[contracts](contracts.md) for abstract obligations and the backend references
for native operations.

## `papilio.infra.db.repositories.base`

### `Reader`

```python
class Reader[U: UnitOfWork](ReaderContract[U]):

    def __init__(self, uow: U) -> None:
        ...
```

### `Repository`

```python
class Repository[T: BaseEntity, U: UnitOfWork](RepositoryContract[T]):

    def __init__(self, uow: U) -> None:
        ...

    async def get_all(self) -> Sequence[T]:
        ...

    def get_all_stream(self, batch_size: int=100) -> AsyncIterator[T]:
        ...
```

### `IdentifiedRepository`

```python
class IdentifiedRepository[T: IdentifiedEntity, U: UnitOfWork](Repository[T, U], IdentifiedRepositoryContract[T]):

    async def get_by_id(self, id: int) -> T | None:
        ...

    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        ...

    async def get_paged(self, limit: int, offset: int=0) -> PagedType[T]:
        ...
```

### `TimestampRepository`

```python
class TimestampRepository[T: TimestampEntity, U: UnitOfWork](Repository[T, U], TimestampRepositoryContract[T]):

    def _time_query(self):
        ...

    def _stream_time(self, condition, batch_size: int) -> AsyncIterator[T]:
        ...

    async def _page_time(self, condition, limit: int, offset: int) -> PagedType[T]:
        ...

    def get_stream_range(self, start: datetime, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_range(self, start: datetime, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_gt(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_gt(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_ge(self, start: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_ge(self, start: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_lt(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_lt(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...

    def get_stream_le(self, end: datetime, batch_size: int=100) -> AsyncIterator[T]:
        ...

    async def get_paged_le(self, end: datetime, limit: int, offset: int=0) -> PagedType[T]:
        ...
```

### `PersistenceRepository`

```python
class PersistenceRepository[T: PersistenceEntity, U: UnitOfWork](IdentifiedRepository[T, U], TimestampRepository[T, U], PersistenceRepositoryContract[T]):

    def _time_query(self):
        ...
```
