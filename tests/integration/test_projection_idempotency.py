import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from elasticsearch.dsl import AsyncDocument, Integer
from elasticsearch.helpers import BulkIndexError

from fastamu.core.config import ESConfig
from fastamu.infra.es.client import ESClient
from fastamu.infra.es.repository import ESRepository
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.projections.convertor import Convertor


@pytest.fixture
async def runtime():
    raw = os.getenv("FASTAMU_ES_TEST_CONFIG")
    if not raw:
        pytest.skip("Set FASTAMU_ES_TEST_CONFIG")
    config = ESConfig.model_validate_json(raw)
    es = ESClient(**config.model_dump())
    name = "test-projection-idempotency-" + uuid4().hex

    class Document(AsyncDocument):
        value = Integer()

        class Index:
            name = "placeholder"

    Document.Index.name = name
    Document._index._name = name

    class Repository(ESRepository[Document]):
        pass

    class Converter(Convertor):
        def convert(self, source):
            return Document(meta={"id": str(source.id)}, value=source.value)

    repo = Repository(es)
    await repo.init()
    try:
        yield SimpleNamespace(
            es=es, repo=repo, converter=Converter(), name=name
        )
    finally:
        await es.client.indices.delete(index=name)
        await es.close()


async def values(runtime):
    await runtime.es.client.indices.refresh(index=runtime.name)
    response = await runtime.es.client.search(
        index=runtime.name, query={"match_all": {}}
    )
    return {
        hit["_id"]: hit["_source"]["value"] for hit in response["hits"]["hits"]
    }


async def test_single_and_delete_repeat_without_extra_documents(runtime):
    class Single(AbstractProjection):
        async def _db_query(self, id):
            return SimpleNamespace(id=id, value=10)

        async def _es_query(self, document):
            await runtime.repo.save(document)

    class Delete(AbstractUnProjection):
        async def _es_query(self, id):
            await runtime.repo.bulk_delete([str(id)])

    projection = Single(runtime.converter)
    await asyncio.gather(*(projection.project(1) for _ in range(4)))
    assert await values(runtime) == {"1": 10}
    await asyncio.gather(*(Delete().unproject(1) for _ in range(4)))
    assert await values(runtime) == {}


@pytest.mark.parametrize("kind", ["batch", "fanout"])
async def test_partial_bulk_failure_can_be_replayed(runtime, kind):
    source = [
        SimpleNamespace(id=1, value=10),
        SimpleNamespace(id=2, value=2**40),
    ]

    class Batch(AbstractBatchProjection):
        async def _db_query(self, ids):
            return source

        async def _es_query(self, documents):
            await runtime.repo.bulk_insert(documents)

    class Fanout(AbstractFanoutProjection):
        async def _db_query(self, id):
            return source

        async def _es_query(self, documents):
            await runtime.repo.bulk_insert(documents)

    async def run():
        if kind == "batch":
            await Batch(runtime.converter).batch_project([1, 2, 1])
        else:
            await Fanout(runtime.converter).project(1)

    with pytest.raises(BulkIndexError):
        await run()
    assert await values(runtime) == {"1": 10}
    source[1].value = 20
    await run()
    await run()
    assert await values(runtime) == {"1": 10, "2": 20}
