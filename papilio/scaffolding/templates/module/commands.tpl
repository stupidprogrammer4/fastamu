from papilio.infra.db.tools.decorators import transactional
from <<PKG>>.<<M>>.domain.dtos import <<P>>Create
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository


class <<P>>CreateCommand:
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    @transactional
    async def execute(self, data: <<P>>Create) -> <<P>>Model:
        return await self.repo.create(<<P>>Model.model_validate(data.to_row()))
