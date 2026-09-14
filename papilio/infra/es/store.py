from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from typing import Any, Literal, cast

from elastic_transport import ObjectApiResponse
from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.dsl import (
    AsyncDocument,
    AsyncIndex,
    AsyncMultiSearch,
    AsyncSearch,
    AsyncUpdateByQuery,
)
from elasticsearch.helpers import async_bulk, async_streaming_bulk

from .client import ESClient

type Items[T] = Iterable[T] | AsyncIterable[T]
type Action = dict[str, Any]
type VersionType = Literal["external", "external_gte"]


async def _iterate[T](items: Items[T]) -> AsyncIterator[T]:
    if isinstance(items, AsyncIterable):
        async for item in items:
            yield item
    else:
        for item in items:
            yield item


class ESStore[TDoc: AsyncDocument]:
    """Document operations and native DSL tools on an explicit connection.

    Subclasses declare ``document = Product``. The generic parameter provides
    typing only; it never selects the document at runtime. The provider owns
    the client lifecycle. Constructing a store never creates an index.
    """

    document: type[TDoc]

    def __init__(self, es: ESClient) -> None:
        if not isinstance(
            getattr(self, "document", None), type
        ) or not issubclass(self.document, AsyncDocument):
            raise TypeError("Declare document as an AsyncDocument subclass")
        self.client: AsyncElasticsearch = es.client

    def index(self) -> AsyncIndex:
        """A bound index copy, including mappings and settings."""
        return self.document._index.clone(using=self.client)

    async def init(self, *, index: str | None = None) -> None:
        await self.document.init(using=self.client, index=index)

    def search(self, *, index: str | None = None) -> AsyncSearch[TDoc]:
        """Full query DSL, including aggs, kNN, PIT and delete-by-query."""
        return self.document.search(using=self.client, index=index)

    def msearch(self) -> AsyncMultiSearch[TDoc]:
        """Add native searches and execute one multi-search request."""
        return AsyncMultiSearch(
            using=self.client, index=self.document._default_index()
        )

    def update_by_query(self) -> AsyncUpdateByQuery:
        return self.index().updateByQuery()

    async def esql(self, query: str, **options: Any) -> ObjectApiResponse[Any]:
        """Execute native ES|QL; returns columns/values, not document models.

        The caller supplies the query's FROM index. ES|QL is not available
        through the document DSL in the supported 8.19.3 distribution.
        """
        return await self.client.esql.query(query=query, **options)

    async def get(self, id: str, **options: Any) -> TDoc | None:
        """Missing documents return None by default; errors remain visible."""
        try:
            return await self.document.get(id, using=self.client, **options)
        except NotFoundError:
            return None

    async def mget(
        self,
        docs: Iterable[str | Action],
        *,
        missing: Literal["none", "skip", "raise"] = "none",
        **options: Any,
    ) -> list[TDoc | None]:
        """Ordered multi-get, with native routing/source specifications."""
        specs = [
            dict(doc) if isinstance(doc, dict) else {"_id": doc}
            for doc in docs
        ]
        return await self.document.mget(
            specs, using=self.client, missing=missing, **options
        )

    async def exists(self, id: str, **options: Any) -> bool:
        return await self.document.exists(id, using=self.client, **options)

    async def save(
        self, doc: TDoc, *, skip_empty: bool = False, **options: Any
    ) -> TDoc:
        """Index a whole document with native sequence concurrency metadata."""
        await doc.save(using=self.client, skip_empty=skip_empty, **options)
        return doc

    async def save_version(
        self,
        doc: TDoc,
        version: int,
        *,
        version_type: VersionType,
        **options: Any,
    ) -> TDoc:
        """Index using an external version instead of sequence concurrency.

        ``external`` requires a newer version; ``external_gte`` accepts equals.
        The server validates versions and reports conflicts.
        """
        return await self.save(
            doc,
            version=version,
            version_type=version_type,
            if_seq_no=None,
            if_primary_term=None,
            **options,
        )

    async def create(self, doc: TDoc, **options: Any) -> TDoc:
        """Create only; an existing ID raises ConflictError."""
        return await self.save(doc, op_type="create", **options)

    async def update(self, doc: TDoc, **fields: Any) -> TDoc:
        """Native document update, including its script/upsert options."""
        await doc.update(using=self.client, **fields)
        return doc

    async def patch(
        self, id: str, fields: Mapping[str, Any] | None = None, **options: Any
    ) -> ObjectApiResponse[Any]:
        """Update by ID without a preliminary read; accepts native API options.

        Pass fields for a partial update or script/upsert through options.
        The response retains result, version and sequence metadata.
        """
        if fields is not None:
            options["doc"] = dict(fields)
        options.setdefault("index", self.document._default_index())
        return await self.client.update(id=id, **options)

    async def delete(self, doc: TDoc, **options: Any) -> None:
        await doc.delete(using=self.client, **options)

    async def _actions(
        self,
        items: Items[TDoc | Action],
        *,
        validate: bool,
        skip_empty: bool,
    ) -> AsyncIterator[Action]:
        async for item in _iterate(items):
            action: Action = (
                {"_source": item}
                if isinstance(item, AsyncDocument)
                else dict(item)
            )
            doc = action.get("_source")
            if isinstance(doc, AsyncDocument):
                if validate:
                    doc.full_clean()
                payload = doc.to_dict(include_meta=True, skip_empty=skip_empty)
                action = {**payload, **action, "_source": payload["_source"]}
                if "seq_no" in doc.meta and "primary_term" in doc.meta:
                    action.setdefault("_if_seq_no", doc.meta.seq_no)
                    action.setdefault(
                        "_if_primary_term", doc.meta.primary_term
                    )
            action.setdefault("_index", self.document._default_index())
            yield action

    async def bulk(
        self,
        actions: Items[TDoc | Action],
        *,
        validate: bool = True,
        skip_empty: bool = False,
        **options: Any,
    ) -> tuple[int, int]:
        """Return success/failure counts without accumulating ignored errors.

        Documents use index (create-or-replace); action dictionaries support
        all native operations and metadata. Chunk limits and retry/error policy
        go to the official helper. Real errors raise by default; this is not
        a transaction. The helper's count is actions, not unique documents.
        """
        success, failed = await async_bulk(
            self.client,
            self._actions(actions, validate=validate, skip_empty=skip_empty),
            stats_only=True,
            **options,
        )
        return success, cast(int, failed)

    def stream(
        self,
        actions: Items[TDoc | Action],
        *,
        validate: bool = True,
        skip_empty: bool = False,
        **options: Any,
    ) -> AsyncIterable[tuple[bool, Action]]:
        """Per-action results; use raise_on_error=False to inspect errors.

        Retries can change result order. Results carry IDs; no input-order
        correspondence is promised. Input and chunks are consumed lazily.
        """
        return async_streaming_bulk(
            self.client,
            self._actions(actions, validate=validate, skip_empty=skip_empty),
            **options,
        )

    async def bulk_index(self, docs: Items[TDoc], **options: Any) -> int:
        """Create or replace documents; return successful action count."""
        success, _ = await self.bulk(docs, **options)
        return success

    async def bulk_create(self, docs: Items[TDoc], **options: Any) -> int:
        """Create only; existing IDs are conflicts, never replacements."""

        async def actions() -> AsyncIterator[Action]:
            async for doc in _iterate(docs):
                yield {"_op_type": "create", "_source": doc}

        success, _ = await self.bulk(actions(), **options)
        return success

    async def bulk_update(
        self,
        updates: Mapping[str, dict[str, Any]],
        **options: Any,
    ) -> int:
        """Partial updates by ID; bulk/stream also accept scripts/upserts."""
        actions = (
            {"_op_type": "update", "_id": id, "doc": fields}
            for id, fields in updates.items()
        )
        success, _ = await self.bulk(actions, **options)
        return success

    async def bulk_delete(self, ids: Items[str], **options: Any) -> int:
        """Count successful deletes; absent IDs are ignored by default."""

        async def actions() -> AsyncIterator[Action]:
            async for id in _iterate(ids):
                yield {"_op_type": "delete", "_id": id}

        options.setdefault("ignore_status", (404,))
        success, _ = await self.bulk(actions(), **options)
        return success
