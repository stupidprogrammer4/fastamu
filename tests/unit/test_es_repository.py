from types import SimpleNamespace
from unittest.mock import AsyncMock

from elasticsearch.dsl import AsyncDocument

from fastamu.infra.es.repository import ESRepository


class SearchDocument(AsyncDocument):
    class Index:
        name = "search_documents"


class SearchRepository(ESRepository[SearchDocument]):
    pass


async def test_patch_updates_by_id_without_a_preliminary_read() -> None:
    client = AsyncMock()
    repository = SearchRepository(SimpleNamespace(client=client))

    await repository.patch_by_id("41", {"active": False, "title": None})

    client.update.assert_awaited_once_with(
        index="search_documents",
        id="41",
        doc={"active": False, "title": None},
    )
