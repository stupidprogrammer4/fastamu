from typing import Any

from <<PKG>>.<<M>>.infra.repository import <<P>>ESStore


class <<P>>SearchQuery:
    def __init__(self, store: <<P>>ESStore) -> None:
        self.store = store

    async def execute(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        query = self.store.search()[offset:offset + limit]
        response = await query.execute()
        return [hit.to_dict() for hit in response]
