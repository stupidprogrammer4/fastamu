from typing import Protocol

from <<PKG>>.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class I<<P>>Service(Protocol):
    async def create(self, data: <<P>>Create) -> <<P>>Model: ...

    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model: ...

    async def get_by_id(self, id: int) -> <<P>>Model: ...

    async def remove(self, id: int) -> int: ...
