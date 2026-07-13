from src.common.bases.schemas import BaseOutput


class JobOut(BaseOutput):
    task_id: str


class JobStatusOut(BaseOutput):
    task_id: str
    is_ready: bool
    is_err: bool | None = None
    error: str | None = None


class ScheduledJobOut(BaseOutput):
    schedule_id: str
    task_name: str
    interval: int | None = None
    cron: str | None = None
    kwargs: dict = {}


class RunningJobOut(BaseOutput):
    message_id: str
    consumer: str
    idle_ms: int            # how long it's been in-flight without being acked
    delivery_count: int     # times it was delivered (>1 hints at retries)


class JobsOverviewOut(BaseOutput):
    scheduled_count: int
    running_count: int
    result_count: int
    scheduled: list[ScheduledJobOut]
    running: list[RunningJobOut]
