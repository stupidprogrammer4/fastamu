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
from papilio.infra.es.provider import ESProvider
from papilio.api.application import create_app

assert settings.es is not None
app = create_app(settings, providers=[ESProvider(settings.es)])
```

For a secured cluster, supply the appropriate `username`/`password` or `api_key`, and optionally `ca_certs`. One client is shared for the app lifetime and closed on shutdown.

## Define a document and repository

```python
from elasticsearch.dsl import AsyncDocument, Integer, Keyword, Text
from papilio.infra.es.repository import ESRepository


class ProductDocument(AsyncDocument):
    sku = Keyword()
    title = Text()
    quantity = Integer()

    class Index:
        name = "products"


class ProductSearchRepository(ESRepository[ProductDocument]):
    pass
```

The document type is bound when the repository subclass is created. Register the repository in a module provider with `provide(ProductSearchRepository, scope=Scope.REQUEST)`. Its constructor receives the shared `ESClient`.

Place module documents in `domain/documents.py` for discovery. At application startup, configured ES causes the bootstrapper to initialize discovered indexes; externally managed documents can use `__external__ = True`. Initialization errors are logged by the bootstrapper, so a started API alone is not proof that all indexes are ready. For explicit setup, `await repo.init()` is also available.

## Save and search

Given an injected `ProductSearchRepository` named `repo`:

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

An explicit document ID controls replacement identity. `save` indexes a whole document, while `patch_by_id` updates supplied fields without first loading the document. `get` returns a document or `None`. Search visibility follows Elasticsearch refresh behavior; `refresh="wait_for"` here is an explicit example choice, not a framework default.

## Bulk tools

```python
inserted = await repo.bulk_insert(
    [ProductDocument(meta={"id": "43"}, sku="PEN", title="Pen", quantity=3)],
    refresh=False,
)
updated = await repo.bulk_update({"43": {"quantity": 5}}, refresh=False)
deleted = await repo.bulk_delete(["43"], refresh=False)
```

These operations return counts and can raise bulk errors. A bulk request is not an all-or-nothing transaction. `bulk_delete` ignores absent document IDs, but does not hide arbitrary server failures. Choose batch size and recovery behavior in the caller. For query DSL, aggregations or custom mappings, use the underlying Elasticsearch tools.

## What the CQRS template does

```bash
papilio new search_shop --dir /tmp/papilio-learning/search_shop --cqrs
cd /tmp/papilio-learning/search_shop
papilio module product --cqrs
```

The module includes SQL persistence, a command path, an ES query path and a search route. Complete document fields and application logic. A successful SQL write does not by itself create a searchable document.

Papilio currently has no publisher, projection registry, repair scheduler, outbox or event runtime. Choose when to index and how to recover failures in your own application or a separately implemented task system. A SQL transaction cannot make a remote ES request atomic with its commit.

[Elasticsearch API reference](../reference/elasticsearch.md)
