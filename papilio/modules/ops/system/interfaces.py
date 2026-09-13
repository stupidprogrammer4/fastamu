from typing import Protocol

from papilio.modules.ops.system.app.results import (
    HealthOut,
    SystemInfoOut,
)


class ISystemService(Protocol):
    async def health(self) -> HealthOut: ...

    async def info(self) -> SystemInfoOut: ...
