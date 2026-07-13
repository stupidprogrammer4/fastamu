from typing import Protocol

from src.modules.ops.jobs.domain.schemas import JobStatusOut, JobsOverviewOut, RunningJobOut


class IJobService(Protocol):
    async def get_status(self, task_id: str) -> JobStatusOut: ...

    async def overview(self) -> JobsOverviewOut: ...

    async def running(self) -> list[RunningJobOut]: ...
