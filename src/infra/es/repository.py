from collections.abc import AsyncIterator, Sequence
from typing import Any, Generic, TypeVar, get_args, get_origin

from elasticsearch import NotFoundError
from elasticsearch.dsl import AsyncDocument, AsyncSearch

from .client import ESClient

TDoc = TypeVar("TDoc", bound=AsyncDocument)


class ESRepository(Generic[TDoc]):
    """Generic CRUD + search over an `elasticsearch.dsl.AsyncDocument`.

    Parameterize with the document type and the index is taken from it::

        class ProductRepository(ESRepository[Product]):
            ...
    """

    __document__: type[TDoc]

    def __init__(self, es: ESClient) -> None:
        self._using = es.client

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", []):
            origin = get_origin(base)
            args = get_args(base)

            if not origin or not args:
                continue

            if isinstance(args[0], TypeVar):
                continue

            if isinstance(origin, type) and issubclass(origin, ESRepository):
                cls.__document__ = args[0]
                break

    async def init(self) -> None:
        """Create the index from the document's mapping."""
        await self.__document__.init(using=self._using)

    async def save(self, doc: TDoc) -> TDoc:
        """Index a document — create, or full-replace by its id."""
        await doc.save(using=self._using)
        return doc

    async def bulk_insert(self, docs: Sequence[TDoc], *, refresh: bool = False) -> int:
        """Index many documents in a single bulk request; returns the count
        indexed. Pass ``refresh=True`` to make them searchable immediately."""
        async def actions() -> AsyncIterator[TDoc]:
            for doc in docs:
                yield doc

        indexed, _ = await self.__document__.bulk(actions(), using=self._using, refresh=refresh)
        return indexed

    async def get(self, id: str) -> TDoc | None:
        """Fetch by id, or ``None`` if it doesn't exist."""
        try:
            result = await self.__document__.get(id, using=self._using)
            return result
        except NotFoundError:
            return None

    async def update(self, doc: TDoc, **fields: Any) -> TDoc:
        """Partial update of an existing document."""
        await doc.update(using=self._using, **fields)
        return doc

    async def delete(self, doc: TDoc) -> None:
        await doc.delete(using=self._using)

    async def exists(self, id: str) -> bool:
        result = await self.__document__.exists(id, using=self._using)
        return result

    def search(self) -> AsyncSearch[TDoc]:
        """A search bound to this client — build the query and ``await .execute()``."""
        return self.__document__.search(using=self._using)


TESRepository = TypeVar("TESRepository", bound=ESRepository)
