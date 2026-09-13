from typing import Any

from <<PKG>>.<<M>>.infra.repository import <<P>>ESRepository


class <<P>>SearchQuery:
    def __init__(self, repo: <<P>>ESRepository) -> None:
        self.repo = repo

    async def execute(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        query = self.repo.search()[offset:offset + limit]
        response = await query.execute()
        return [hit.to_dict() for hit in response]
