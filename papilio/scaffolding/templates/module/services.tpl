from papilio.services import BaseIDService
from papilio.infra.db.tools.decorators import transactional
from <<PKG>>.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository


class <<P>>Service(BaseIDService[<<P>>Model]):
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    @transactional
    async def create(self, data: <<P>>Create) -> <<P>>Model:
        return await self.repo.create(<<P>>Model.model_validate(data.to_row()))

    @transactional
    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model:
        fields = self._check_not_empty_dict(data.to_row())
        result = await self.repo.update_row_by_id(id, <<P>>Model.patch(**fields))
        return self._check_for_id_existence(id, result)

    async def get_by_id(self, id: int) -> <<P>>Model:
        return self._check_for_id_existence(id, await self.repo.get_by_id(id))

    @transactional
    async def remove(self, id: int) -> int:
        return int(await self.repo.remove_by_id(id) is not None)
