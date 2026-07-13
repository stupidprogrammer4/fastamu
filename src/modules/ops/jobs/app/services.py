from datetime import timedelta

from redis.exceptions import ResponseError
from taskiq import AsyncResultBackend, ScheduleSource

from src.infra.redis.client import RedisClient
from src.modules.ops.jobs.domain.schemas import (
    JobStatusOut,
    JobsOverviewOut,
    RunningJobOut,
    ScheduledJobOut,
)

# result-backend key prefix (set on the broker), used to count stored results
_RESULT_PREFIX = "taskiq_result"


def _interval_seconds(interval: int | timedelta | None) -> int | None:
    """Normalize a schedule's interval to whole seconds."""
    result: int | None = int(interval.total_seconds()) if isinstance(interval, timedelta) else interval
    return result


class JobService:
    """Read-only view over the task system: a job's result by id, the scheduled
    jobs, the in-flight (running) jobs, and how many results are stored."""

    def __init__(
        self,
        result_backend: AsyncResultBackend,
        schedule_source: ScheduleSource,
        redis: RedisClient,
        stream_name: str,
        group_name: str,
    ) -> None:
        self.result_backend = result_backend
        self.schedule_source = schedule_source
        self.redis = redis
        self.stream_name = stream_name      # broker's redis stream
        self.group_name = group_name        # broker's consumer group

    async def get_status(self, task_id: str) -> JobStatusOut:
        """Get a single job's status (and error, once finished) by its task id.

        Args:
            task_id (str): The job's task id (returned when it was enqueued).
        Returns:
            (JobStatusOut): Whether it's ready and, if so, whether it errored.
        """
        ready = await self.result_backend.is_result_ready(task_id)
        status = JobStatusOut(task_id=task_id, is_ready=ready)
        if ready:
            result = await self.result_backend.get_result(task_id, with_logs=False)
            status.is_err = result.is_err
            status.error = str(result.error) if result.error is not None else None
        return status

    async def overview(self) -> JobsOverviewOut:
        """Get an overview of the task system: scheduled + running jobs + result count.

        Returns:
            (JobsOverviewOut): The scheduled and running jobs with their counts.
        """
        schedules = await self.schedule_source.get_schedules()
        scheduled = [
            ScheduledJobOut(
                schedule_id=schedule.schedule_id,
                task_name=schedule.task_name,
                interval=_interval_seconds(schedule.interval),
                cron=schedule.cron,
                kwargs=schedule.kwargs,
            )
            for schedule in schedules
        ]
        running = await self.running()
        result_count = await self._count_results()
        return JobsOverviewOut(
            scheduled_count=len(scheduled),
            running_count=len(running),
            result_count=result_count,
            scheduled=scheduled,
            running=running,
        )

    async def running(self) -> list[RunningJobOut]:
        """Get the jobs currently being processed (delivered but not yet acked).

        Returns:
            (list[RunningJobOut]): The in-flight jobs; empty if none / no worker yet.
        """
        try:
            pending = await self.redis.client.xpending_range(
                self.stream_name, self.group_name, min="-", max="+", count=100
            )
        except ResponseError:
            return []                           # NOGROUP — no worker has consumed yet
        return [
            RunningJobOut(
                message_id=str(entry["message_id"]),
                consumer=str(entry["consumer"]),
                idle_ms=int(entry["time_since_delivered"]),
                delivery_count=int(entry["times_delivered"]),
            )
            for entry in pending
        ]

    async def _count_results(self) -> int:
        """Count stored job results in redis (excludes progress keys)."""
        count = 0
        async for key in self.redis.client.scan_iter(match=f"{_RESULT_PREFIX}:*"):
            if "progress" not in key:
                count += 1
        return count
