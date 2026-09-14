# Elasticsearch and CQRS

Install the `es` extra to use Elasticsearch tools. Select `--cqrs` when generating a project if you want PostgreSQL command and Elasticsearch query templates together. This creates the two paths, not automatic synchronization between them.

## Connect Elasticsearch

Add an ES section to your full configuration and register `ESProvider`:

```yaml
es:
  hosts: [http://127.0.0.1:9200]
  verify_certs: true
```

```python
from papilio.providers.es import ESProvider
from papilio.api.application import create_app

assert settings.es is not None
app = create_app(settings, providers=[ESProvider(settings.es)])
```

For a secured cluster, supply the appropriate `username`/`password` or `api_key`, and optionally `ca_certs`. One client is shared for the app lifetime and closed on shutdown.

## Define a document and store

```python
from elasticsearch.dsl import AsyncDocument, Integer, Keyword, Text
from papilio.infra.es.store import ESStore


class ProductDocument(AsyncDocument):
    sku = Keyword()
    title = Text()
    quantity = Integer()

    class Index:
        name = "products"


class ProductStore(ESStore[ProductDocument]):
    document = ProductDocument
```

The `document` attribute binds the model explicitly; the generic parameter supplies typing. Register the store in a module provider with `provide(ProductStore, scope=Scope.REQUEST)`. Its constructor receives the shared `ESClient`.

Place module documents in `domain/documents.py` for discovery. To initialize discovered indexes, opt into an [ES lifespan](providers.md#choose-startup-work-explicitly), as the generated ES/CQRS entry point does; externally managed documents can use `__external__ = True`. Initialization errors are logged by the bootstrapper, so a started API alone is not proof that all indexes are ready. For explicit setup, `await repo.init()` is also available.

## Save and search

Given an injected `ProductStore` named `repo`:

```python
await repo.save(
    ProductDocument(meta={"id": "42"}, sku="BOOK", title="Notebook", quantity=2),
    refresh="wait_for",
)
search = repo.search().query("match", title="Notebook")
search = search.sort("sku")[:20]
response = await search.execute()
items = [hit.to_dict() for hit in response]
```

An explicit document ID controls replacement identity. `save` indexes a whole document, while `patch` updates supplied fields without first loading the document. `get` returns a document or `None`. Search visibility follows Elasticsearch refresh behavior; `refresh="wait_for"` here is an explicit example choice, not a framework default.

## Bulk tools

```python
inserted = await repo.bulk_index(
    [ProductDocument(meta={"id": "43"}, sku="PEN", title="Pen", quantity=3)],
    refresh=False,
)
updated = await repo.bulk_update({"43": {"quantity": 5}}, refresh=False)
deleted = await repo.bulk_delete(["43"], refresh=False)
```

These operations return counts and can raise bulk errors. A bulk request is not an all-or-nothing transaction. `bulk_delete` ignores absent document IDs, but does not hide arbitrary server failures. Pass `chunk_size`, `max_chunk_bytes`, `max_retries`, `refresh` and other native helper options explicitly. Retry settings for individual bulk items are separate from client transport retries. Counts describe successful actions, not unique IDs. `bulk_index` replaces existing documents; `bulk_create` instead reports conflicts on existing IDs.

## Versioned writes

`save(doc)` uses the document's native sequence/primary-term metadata when present.
`save_version` selects external versioning instead, including for a previously
loaded document. It updates the document's response metadata like `save`:

```python
await repo.save_version(doc, 12, version_type="external")
```

Choose the policy explicitly: `external` requires a strictly greater version;
`external_gte` also allows an equal version to replace the document. Both reject
older versions with the native `ConflictError`. There is no automatic conflict
recovery. Use `create(doc)` when replacing an existing ID must fail regardless
of version. `save`, `save_version` and document bulk preserve empty fields by
default; `skip_empty=True` explicitly selects the DSL's stripping behavior.

## Mixed bulk and per-item results

`bulk(actions)` accepts document instances or native action dictionaries from
an iterable or async iterable. It returns `(successful, failed)` counts. Real
item errors raise by default; `raise_on_error=False` returns failure counts.
`stream(actions)` yields the helper's `(ok, item)` results without accumulating
them. Set `raise_on_error=False` there to inspect each item error. Retries may
change result order, so correlate results by ID, not position. In 8.19.3,
item retries require `raise_on_error=False` together with `max_retries`: otherwise
the helper raises a chunk error before it can retry individual rejected items.
Inspect the returned failure counts/items when using this mode.

Native action dictionaries expose `index`, `create`, `update`, and `delete`,
including per-action routing, external versions, sequence tokens, scripts and
upserts. Document values retain validation and metadata; dictionaries are
explicit native requests and are not model-validated. Neither helper updates
input document metadata from bulk responses. For metadata after bulk, use
`stream` results or an explicit read.

`bulk_index(docs)`, `bulk_create(docs)` and `bulk_delete(ids)` also accept async
inputs. `bulk_update({id: fields})` is a convenience for partial updates; use
`bulk` or `stream` for streaming updates and richer action options. No helper
promises a single request for an arbitrary input size. Helpers buffer chunks;
validation and serialization still do CPU work on the event loop.

## DSL capability map

Store methods return the original DSL objects; their native methods and results
remain available. Builders perform no network work until explicitly executed.

| Capability | Entry point |
| --- | --- |
| Queries, filters, exclusions, nested/boolean queries | `repo.search()` with native `Q` and query classes |
| Aggregations, buckets, metrics, pipelines | `search.aggs` and native `A`/aggregation classes |
| Sorting, source filtering, script fields, extra parameters | Native search methods, `.extra()` and `.params()` |
| Highlighting, suggestions, collapsing | `.highlight()`, `.suggest()`, `.collapse()` |
| Vector search and ranking | `.knn()`, `.rank()`; subject to server capabilities |
| Pages and stable sequential iteration | Slicing, `.search_after()`, `.point_in_time()`, `.iterate()` |
| Scroll iteration, count, delete-by-query | `.scan()`, `await search.count()`, `await search.delete()` |
| Multiple searches | `repo.msearch().add(search)` then `.execute()` |
| Scripted update-by-query | `repo.update_by_query().query(...).script(...)` then `.execute()` |
| Multi-get, missing-ID policy and routing | `await repo.mget(ids_or_specs, missing="none")` |
| In-memory document updates and scripts | `await repo.update(doc, ...)` uses `AsyncDocument.update` |
| ID-based partial update, scripts, upsert, concurrency options | `await repo.patch(id, fields, **options)` returns the native API response |
| Index creation, mappings, settings, aliases and maintenance | `repo.index()` returns a bound `AsyncIndex` clone |
| Legacy/composable index templates | `repo.index().as_template(...)` / `.as_composable_template(...)` |
| Fields, inner documents, analyzers and mapping definitions | Import native DSL classes; use them on documents or the index clone |
| Faceted search | Subclass native `AsyncFacetedSearch`; bind its search as below |
| ES|QL | `await repo.esql("FROM products ...")` returns raw columns/values |
| Other Elasticsearch APIs and request options | `repo.client`, including `.options(...)` |

Use `.iterate()` for large sequential reads where a stable snapshot matters.
It uses PIT/search_after, unlike deep offset pagination. In the installed
8.19.3 DSL, its PIT cleanup runs on normal completion but not on an early
`break`/exception; an abandoned PIT then depends on its keep-alive expiry. For
early termination with deterministic cleanup, manage PIT explicitly through
`repo.client.open_point_in_time`/`close_point_in_time` in `try/finally`. This
store does not patch the upstream iterator or promise cleanup it cannot provide. Native search responses
retain aggregations, highlights, suggestions and hit metadata; the store never
reduces these to a list of source dictionaries.

An index clone keeps document mappings/settings while avoiding changes to the
class-level index or another store's connection. Applying that clone still needs
an explicit `create()`/`save()` call. Mapping declarations use native
`AsyncMapping` or `Mapping`; they are not an extra Papilio schema system.

For faceted search, use the DSL extension point instead of global connection
aliases or another framework wrapper:

```python
from elasticsearch.dsl import AsyncFacetedSearch, FacetedResponse, TermsFacet

class ProductFacets(AsyncFacetedSearch):
    facets = {"sku": TermsFacet(field="sku")}

    def __init__(self, store: ProductStore, **options):
        self.store = store
        super().__init__(**options)

    def search(self):
        return self.store.search().response_class(FacetedResponse)
```

The installed 8.19.3 package exposes document ES|QL method names but lacks their
required `elasticsearch.dsl.esql` module. `repo.esql` therefore calls the official
client API directly. It does not claim a typed document stream: the server
response is buffered and contains columns/values. The query itself specifies its
index. Server/version/license support for individual features must be checked
against the deployment; exposing a builder does not enable a server feature.

## Migration from ESRepository

- Import `ESStore` from `papilio.infra.es.store` and declare `document = MyDocument`.
- Replace `bulk_insert` with `bulk_index` to preserve create-or-replace behavior.
  `bulk_create` has distinct create-only semantics.
- Replace `patch_by_id` with `patch`; its result now contains native response
  metadata rather than `None`.
- The shared `ESClient`, optional provider and application-owned index startup
  retain their existing lifecycle. There is no compatibility alias for the old
  repository class/module.

## What the CQRS template does

```bash
papilio new search_shop --dir /tmp/papilio-learning/search_shop --cqrs
cd /tmp/papilio-learning/search_shop
papilio module product --cqrs
```

The module includes SQL persistence, a command path, an ES query path and a search route. Complete document fields and application logic. A successful SQL write does not by itself create a searchable document.

Papilio currently has no publisher, projection registry, repair scheduler, outbox or event runtime. Choose when to index and how to recover failures in your own application or a separately implemented task system. A SQL transaction cannot make a remote ES request atomic with its commit.

[Elasticsearch API reference](../reference/elasticsearch.md)
