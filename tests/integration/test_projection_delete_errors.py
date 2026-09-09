import os
from uuid import uuid4

import pytest
from elasticsearch.dsl import AsyncDocument
from elasticsearch.helpers import BulkIndexError

from fastamu.core.config import ESConfig
from fastamu.infra.es.client import ESClient
from fastamu.infra.es.repository import ESRepository


async def test_bulk_delete_ignores_missing_ids_but_retries_failed_items():
    raw = os.environ.get("FASTAMU_ES_TEST_CONFIG")
    if raw is None:
        pytest.skip("Set FASTAMU_ES_TEST_CONFIG for Elasticsearch tests")
    config = ESConfig.model_validate_json(raw)
    es = ESClient(
        config.hosts,
        username=config.username,
        password=config.password,
        api_key=config.api_key,
        verify_certs=config.verify_certs,
        ca_certs=config.ca_certs,
    )
    name = "test-projection-delete-" + uuid4().hex

    class Document(AsyncDocument):
        class Index:
            name = "placeholder"

    Document.Index.name = name
    Document._index._name = name

    class Repository(ESRepository[Document]):
        pass

    repository = Repository(es)
    await es.client.indices.create(index=name)
    try:
        await es.client.index(index=name, id="one", document={"title": "one"})
        assert await repository.bulk_delete(["one", "absent"]) == 1
        await es.client.index(index=name, id="two", document={"title": "two"})
        await es.client.indices.put_settings(
            index=name, settings={"index.blocks.write": True}
        )
        with pytest.raises(BulkIndexError):
            await repository.bulk_delete(["two"])
        assert await es.client.exists(index=name, id="two")
        await es.client.indices.put_settings(
            index=name, settings={"index.blocks.write": False}
        )
        assert await repository.bulk_delete(["two"]) == 1
    finally:
        try:
            await es.client.indices.delete(index=name)
        finally:
            await es.close()
