from typing import Protocol

from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.app.results import <<P>>Out


class I<<P>>Service(Protocol):
    async def run(self, data: <<P>>Input) -> <<P>>Out: ...
