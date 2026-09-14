import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from elastic_transport import ApiResponseMeta, NodeConfig, TransportApiResponse
from elasticsearch import AsyncElasticsearch, ConflictError, NotFoundError
from elasticsearch.dsl import (
    AsyncDocument,
    AsyncFacetedSearch,
    FacetedResponse,
    Keyword,
    TermsFacet,
    Text,
    ValidationException,
)
from elasticsearch.helpers import BulkIndexError

from papilio.infra.es.store import ESStore


class Product(AsyncDocument):
    title = Text()
    tags = Keyword(multi=True)

    class Index:
        name = "products"
        settings = {"number_of_shards": 1}


class ProductStore(ESStore[Product]):
    document = Product


def response(body, status=200):
    meta = ApiResponseMeta(
        status,
        "1.1",
        {"x-elastic-product": "Elasticsearch"},
        0,
        NodeConfig("http", "localhost", 9200),
    )
    return TransportApiResponse(meta, body)


def saved(version=1):
    return response(
        {
            "_id": "1",
            "_index": "products",
            "result": "created",
            "_version": version,
            "_seq_no": version,
            "_primary_term": 2,
        }
    )


@pytest.fixture
async def wire():
    client = AsyncElasticsearch("http://localhost:9200")
    request = AsyncMock(return_value=saved())
    client.transport.perform_request = request
    yield ProductStore(SimpleNamespace(client=client)), request
    await client.close()


async def test_explicit_document_binding_across_generic_inheritance(wire):
    store, request = wire

    class Tagged[TKey, TDoc: AsyncDocument](ESStore[TDoc]):
        pass

    class Products(Tagged[str, Product]):
        document = Product

    child = Products(SimpleNamespace(client=store.client))
    assert child.document is Product
    assert child.search().to_dict() == {}
    with pytest.raises(TypeError, match="Declare document"):
        ESStore(SimpleNamespace(client=store.client))
    request.assert_not_called()


async def test_save_preserves_source_and_native_concurrency(wire):
    store, request = wire
    doc = Product(meta={"id": "1", "routing": "tenant"}, title=None, tags=[])
    assert await store.save(doc) is doc
    assert request.call_args.kwargs["body"] == {"title": None, "tags": []}
    assert doc.meta.version == 1
    await store.save(doc)
    query = parse_qs(urlsplit(request.call_args.args[1]).query)
    assert query == {
        "routing": ["tenant"],
        "if_seq_no": ["1"],
        "if_primary_term": ["2"],
    }


@pytest.mark.parametrize("mode", ["external", "external_gte"])
async def test_save_version_uses_external_version_even_on_loaded_document(
    wire, mode
):
    store, request = wire
    doc = Product(meta={"id": "1", "seq_no": 7, "primary_term": 2}, title="x")
    assert await store.save_version(doc, 12, version_type=mode) is doc
    query = parse_qs(urlsplit(request.call_args.args[1]).query)
    assert query == {"version": ["12"], "version_type": [mode]}
    request.return_value = response({"error": "version conflict"}, 409)
    with pytest.raises(ConflictError):
        await store.save_version(doc, 11, version_type=mode)


async def test_create_is_create_only_and_conflicts_are_visible(wire):
    store, request = wire
    doc = Product(meta={"id": "1"}, title="x")
    await store.create(doc)
    assert parse_qs(urlsplit(request.call_args.args[1]).query) == {
        "op_type": ["create"]
    }
    request.return_value = response({"error": "already exists"}, 409)
    with pytest.raises(ConflictError):
        await store.create(Product(meta={"id": "1"}, title="y"))


async def test_patch_separates_fields_and_options_without_read(wire):
    store, request = wire
    result = await store.patch(
        "1",
        {"refresh": "field value", "title": None},
        refresh="wait_for",
        doc_as_upsert=True,
    )
    assert request.await_count == 1
    assert request.call_args.args[:2] == (
        "POST",
        "/products/_update/1?refresh=wait_for",
    )
    assert request.call_args.kwargs["body"] == {
        "doc": {"refresh": "field value", "title": None},
        "doc_as_upsert": True,
    }
    assert result["_version"] == 1


async def test_document_update_delete_and_missing_get(wire):
    store, request = wire
    doc = Product(meta={"id": "1"}, title="old")
    assert await store.update(doc, title="new") is doc
    assert doc.title == "new"
    assert request.call_args.kwargs["body"]["doc"] == {"title": "new"}
    await store.delete(doc)
    assert request.call_args.args[0] == "DELETE"
    assert "if_seq_no=1" in request.call_args.args[1]
    request.return_value = response({"found": False}, 404)
    assert await store.get("absent") is None
    with pytest.raises(NotFoundError):
        await store.delete(Product(meta={"id": "absent"}))


async def test_mget_preserves_order_missing_slots_and_metadata(wire):
    store, request = wire
    request.return_value = response(
        {
            "docs": [
                {
                    "_id": "2",
                    "_index": "products",
                    "found": True,
                    "_source": {"title": "two"},
                    "_seq_no": 4,
                    "_primary_term": 1,
                },
                {"_id": "absent", "found": False},
            ]
        }
    )
    docs = await store.mget([{"_id": "2", "routing": "t"}, "absent"])
    assert isinstance(docs[0], Product)
    assert docs[0].meta.seq_no == 4
    assert docs[1] is None
    assert request.call_args.kwargs["body"]["docs"] == [
        {"_id": "2", "routing": "t"},
        {"_id": "absent"},
    ]


class BulkWire:
    """Only network responses are simulated; DSL/client/helpers are real."""

    def __init__(self, statuses=None):
        self.statuses = iter(statuses) if statuses is not None else None
        self.batches = []

    def __call__(self, method, target, *, body, **kwargs):
        assert method == "PUT" and urlsplit(target).path == "/_bulk"
        lines = iter(body)
        batch = []
        results = []
        for line in lines:
            header = json.loads(line)
            op, meta = next(iter(header.items()))
            source = None if op == "delete" else json.loads(next(lines))
            batch.append((op, meta, source))
            status = next(self.statuses) if self.statuses is not None else 200
            result = {"_id": meta.get("_id", "1"), "status": status}
            if status >= 400:
                result["error"] = {"type": "test_failure"}
            results.append({op: result})
        self.batches.append(batch)
        return response(
            {
                "items": results,
                "errors": any(
                    next(iter(item.values()))["status"] >= 400
                    for item in results
                ),
            }
        )


async def test_bulk_source_metadata_parity_and_async_chunking(wire):
    store, request = wire
    doc = Product(meta={"id": "1", "routing": "t"}, title=None, tags=[])
    await store.save(doc)
    source = request.call_args.kwargs["body"]
    transport = BulkWire()
    request.side_effect = transport

    async def documents():
        for _ in range(5):
            yield doc

    assert await store.bulk_index(documents(), chunk_size=2) == 5
    assert [len(batch) for batch in transport.batches] == [2, 2, 1]
    op, meta, actual = transport.batches[0][0]
    assert op == "index" and actual == source
    assert meta == {
        "_id": "1",
        "_index": "products",
        "routing": "t",
        "if_seq_no": 1,
        "if_primary_term": 2,
    }


async def test_bulk_create_validates_preserves_metadata_and_does_not_mutate(
    wire,
):
    store, request = wire
    transport = BulkWire()
    request.side_effect = transport
    doc = Product(meta={"id": "1", "routing": "t"}, title=None)
    assert await store.bulk_create([doc]) == 1
    op, meta, source = transport.batches[0][0]
    assert op == "create" and meta["_id"] == "1" and meta["routing"] == "t"
    assert source["title"] is None
    action = {"_op_type": "index", "_index": "other", "_source": doc}
    await store.bulk([action])
    assert action["_source"] is doc
    assert transport.batches[1][0][1]["_index"] == "other"

    class Required(AsyncDocument):
        title = Text(required=True)

    with pytest.raises(ValidationException):
        await store.bulk_create([Required()])


async def test_bulk_mixed_results_counts_and_errors(wire):
    store, request = wire
    request.side_effect = BulkWire([200, 404, 200])
    assert await store.bulk_delete(str(i) for i in range(3)) == 2
    request.side_effect = BulkWire([200, 400])
    with pytest.raises(BulkIndexError):
        await store.bulk_delete(["ok", "bad"])
    request.side_effect = BulkWire([200, 409])
    assert await store.bulk(
        [
            {
                "_op_type": "update",
                "_id": "1",
                "script": {"source": "ctx.op='noop'"},
            },
            {"_op_type": "create", "_id": "2", "_source": {"title": "x"}},
        ],
        raise_on_error=False,
    ) == (1, 1)


async def test_stream_is_lazy_returns_per_item_errors_and_retries_429(wire):
    store, request = wire
    consumed = []

    async def docs():
        for i in range(100):
            consumed.append(i)
            yield Product(meta={"id": str(i)}, title="x")

    transport = BulkWire()
    request.side_effect = transport
    results = store.stream(docs(), chunk_size=2)
    assert consumed == []
    async for ok, result in results:
        assert ok
        break
    await results.aclose()
    assert len(consumed) <= 3  # The helper may look ahead by one action.
    assert len(transport.batches) == 1

    transport = BulkWire([429, 200])
    request.side_effect = transport
    results = [
        result
        async for result in store.stream(
            [Product(title="x")],
            max_retries=1,
            initial_backoff=0,
            raise_on_error=False,
        )
    ]
    assert results[0][0] is True and len(transport.batches) == 2
    request.side_effect = BulkWire([409])
    results = [
        result
        async for result in store.stream(
            [Product(title="x")],
            raise_on_error=False,
        )
    ]
    assert results[0][0] is False
    assert results[0][1]["index"]["status"] == 409


async def test_native_search_tools_keep_typed_hits_and_complete_response(wire):
    store, request = wire
    search = store.search().query("match", title="x").filter("term", tags="a")
    search = (
        search.sort("title.keyword").highlight("title").source(["title"])[:5]
    )
    search.aggs.bucket("tags", "terms", field="tags")
    search = search.suggest("titles", "x", term={"field": "title"})
    request.return_value = response(
        {
            "hits": {
                "hits": [
                    {
                        "_id": "1",
                        "_index": "products",
                        "_source": {"title": "x"},
                    }
                ]
            },
            "aggregations": {"tags": {"buckets": []}},
        }
    )
    result = await search.execute()
    assert isinstance(result.hits[0], Product)
    assert result.aggregations.tags.buckets == []
    body = request.call_args.kwargs["body"]
    assert all(
        key in body
        for key in ("query", "sort", "highlight", "aggs", "suggest")
    )
    assert body["size"] == 5
    knn = store.search().knn("vector", 3, 10, query_vector=[1.0, 0.0])
    assert knn.to_dict()["knn"]["k"] == 3


async def test_index_templates_msearch_and_update_by_query(wire):
    store, request = wire
    index = store.index()
    index.settings(number_of_replicas=0)
    index.aliases(read_products={})
    assert "title" in index.to_dict()["mappings"]["properties"]
    assert "number_of_replicas" not in store.index().to_dict()["settings"]
    assert "read_products" not in Product._index.to_dict().get("aliases", {})
    assert index.as_composable_template("products_template").to_dict()
    await index.refresh()
    assert request.call_args.args[:2] == ("POST", "/products/_refresh")
    request.return_value = response({"responses": [{"hits": {"hits": []}}]})
    results = await store.msearch().add(store.search()).execute()
    assert len(results) == 1
    request.return_value = response({"updated": 2})
    result = (
        await store.update_by_query()
        .filter("term", tags="old")
        .script(
            source="ctx._source.tags = params.tags", params={"tags": ["new"]}
        )
        .execute()
    )
    assert result.updated == 2
    assert "/products/_update_by_query" == request.call_args.args[1]


async def test_esql_uses_native_client_api(wire):
    store, request = wire
    request.return_value = response(
        {"columns": [{"name": "title", "type": "keyword"}], "values": [["x"]]}
    )
    result = await store.esql("FROM products | KEEP title")
    assert result["values"] == [["x"]]
    assert request.call_args.args[:2] == ("POST", "/_query")


async def test_pit_is_closed_after_complete_iteration(wire):
    store, request = wire
    request.side_effect = [
        response({"id": "pit-1"}),
        response(
            {
                "pit_id": "pit-2",
                "hits": {
                    "hits": [
                        {
                            "_id": "1",
                            "_index": "products",
                            "_source": {"title": "x"},
                            "sort": [1],
                        },
                    ]
                },
            }
        ),
        response({"pit_id": "pit-2", "hits": {"hits": []}}),
        response({"succeeded": True, "num_freed": 1}),
    ]
    iterator = store.search().iterate()
    docs = [doc async for doc in iterator]
    assert len(docs) == 1 and isinstance(docs[0], Product)
    assert request.call_args.args[:2] == ("DELETE", "/_pit")
    assert request.call_args.kwargs["body"]["id"] in ("pit-1", "pit-2")


async def test_native_facets_bind_to_the_store_without_global_connections(
    wire,
):
    store, request = wire

    class ProductFacets(AsyncFacetedSearch):
        facets = {"tags": TermsFacet(field="tags")}

        def __init__(self, store, **options):
            self.store = store
            super().__init__(**options)

        def search(self):
            return self.store.search().response_class(FacetedResponse)

    request.return_value = response(
        {
            "hits": {"hits": []},
            "aggregations": {
                "_filter_tags": {
                    "tags": {
                        "buckets": [
                            {"key": "a", "doc_count": 2},
                        ]
                    }
                }
            },
        }
    )
    result = await ProductFacets(store).execute()
    assert result.facets.tags == [("a", 2, False)]
    assert request.call_args.args[1] == "/products/_search"


async def test_bulk_empty_updates_and_byte_limits(wire):
    store, request = wire
    assert await store.bulk([]) == (0, 0)
    request.assert_not_called()
    transport = BulkWire()
    request.side_effect = transport
    assert await store.bulk_update({"1": {"title": None}}) == 1
    assert transport.batches[0][0] == (
        "update",
        {"_index": "products", "_id": "1"},
        {"doc": {"title": None}},
    )
    transport.batches.clear()
    await store.bulk_index(
        [Product(title="x" * 100), Product(title="y" * 100)],
        max_chunk_bytes=200,
    )
    assert [len(batch) for batch in transport.batches] == [1, 1]


async def test_stores_keep_connections_separate(wire):
    first, request = wire
    client = AsyncElasticsearch("http://other:9200")
    other_request = AsyncMock(return_value=response({"hits": {"hits": []}}))
    client.transport.perform_request = other_request
    second = ProductStore(SimpleNamespace(client=client))
    try:
        first_search = first.search()
        await second.search().execute()
        request.assert_not_called()
        request.return_value = response({"hits": {"hits": []}})
        await first_search.execute()
        assert request.await_count == other_request.await_count == 1
    finally:
        await client.close()
