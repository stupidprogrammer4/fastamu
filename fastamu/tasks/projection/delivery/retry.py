"""Apply the application's policy through native Taskiq middleware hooks."""

import asyncio
from typing import TYPE_CHECKING

from taskiq import NoResultError, TaskiqMiddleware
from taskiq.kicker import AsyncKicker

from fastamu.tasks.retry import failure_headers

if TYPE_CHECKING:
    from fastamu.tasks.projection.broker import ProjectionBroker


class ProjectionRetry(TaskiqMiddleware):
    broker: "ProjectionBroker"

    async def on_error(self, message, result, exception):
        token = message.labels.pop("_fastamu_delivery", None)
        policy = self.broker.retry_policies.get(message.task_name)
        if policy is None or isinstance(exception, NoResultError):
            return
        if not isinstance(exception, Exception):
            await self.broker.requeue(token)
            raise exception
        attempt = int(message.labels.get("fastamu_attempt", 0)) + 1
        try:
            decision = policy.decide(exception, attempt)
            message.labels = failure_headers(
                message.labels, exception, attempt, self.broker.retry_config
            )
            if decision.delay is None:
                await self.broker.park(message)
            else:
                await (
                    AsyncKicker(message.task_name, self.broker, message.labels)
                    .with_task_id(message.task_id)
                    .with_labels(
                        fastamu_retry_delay=decision.delay,
                        fastamu_retry_max_delay=decision.max_delay
                        or decision.delay,
                    )
                    .kiq(*message.args, **message.kwargs)
                )
                result.error = NoResultError()
        except Exception:
            await asyncio.sleep(self.broker.retry_config.handoff_failure_delay)
            await self.broker.requeue(token)
            raise
