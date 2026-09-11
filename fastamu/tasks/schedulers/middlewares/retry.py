"""Schedule job retries using the policy declared on the registered task."""

import asyncio
from datetime import UTC, datetime, timedelta

from taskiq import NoResultError, ScheduleSource, TaskiqMiddleware
from taskiq.kicker import AsyncKicker

from fastamu.core.config import RetryTransportConfig
from fastamu.messaging.retry import RetryPolicy
from fastamu.tasks.retry import failure_headers


class ScheduledRetry(TaskiqMiddleware):
    def __init__(self, source: ScheduleSource, config: RetryTransportConfig):
        super().__init__()
        self.source = source
        self.config = config

    async def startup(self):
        await self.source.startup()

    async def shutdown(self):
        await self.source.shutdown()

    async def on_error(self, message, result, exception):
        if isinstance(exception, NoResultError):
            return
        if not isinstance(exception, Exception):
            raise exception
        task = self.broker.find_task(message.task_name)
        policy = task.labels.get("retry_policy") if task is not None else None
        if policy is None:
            return
        if not isinstance(policy, RetryPolicy):
            raise TypeError("Task retry_policy must be a RetryPolicy")
        attempt = int(message.labels.get("fastamu_attempt", 0)) + 1
        decision = policy.decide(exception, attempt)
        if decision.delay is None:
            return
        labels = failure_headers(
            message.labels, exception, attempt, self.config
        )
        labels.pop("retry_policy", None)
        async with asyncio.timeout(self.config.publish_timeout):
            await (
                AsyncKicker(message.task_name, self.broker, labels)
                .with_task_id(message.task_id)
                .schedule_by_time(
                    self.source,
                    datetime.now(UTC) + timedelta(seconds=decision.delay),
                    *message.args,
                    **message.kwargs,
                )
            )
        result.error = NoResultError()
