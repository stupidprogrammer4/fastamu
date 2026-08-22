from typing import Protocol

from fastamu.modules.ops.system.domain.schemas import HealthOut, SystemInfoOut


class ISystemService(Protocol):
    async def health(self) -> HealthOut: ...

    async def info(self) -> SystemInfoOut: ...
