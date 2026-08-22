from typing import Any, Protocol

from fastamu.modules.ops.jobs.domain.schemas import (
    JobsOverviewOut,
    JobStatusOut,
    RunningJobOut,
)


class IJobService(Protocol):
    async def get_status(self, task_id: str) -> JobStatusOut: ...

    async def get_result(self, task_id: str) -> Any: ...

    async def overview(self) -> JobsOverviewOut: ...

    async def running(self) -> list[RunningJobOut]: ...
