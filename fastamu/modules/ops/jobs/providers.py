from dishka import Provider, Scope, provide
from taskiq import ScheduleSource

from fastamu.infra.redis.client import RedisClient
from fastamu.modules.ops.jobs.app.services import JobService
from fastamu.modules.ops.jobs.interfaces import IJobService
from fastamu.tasks.schedulers.broker import broker


class JobProvider(Provider):
    @provide(scope=Scope.APP)
    def job_service(
        self, schedule_source: ScheduleSource, redis: RedisClient
    ) -> IJobService:
        return JobService(
            broker.result_backend,
            schedule_source,
            redis,
            broker.queue_name,
            broker.consumer_group_name,
        )
