"""Retry the current delivery without letting subsequent tasks overtake it.

A delivery that exhausts its immediate retries is stored durably before ACK.
"""

import asyncio
import logging
import time

from taskiq import AckableMessage, TaskiqMiddleware
from taskiq.receiver import Receiver
from taskiq.utils import maybe_awaitable

from fastamu.core.config import get_settings
from fastamu.infra.db.versions import ProjectionExpired, ProjectionObsolete
from fastamu.tasks.projection.recovery import ProjectionRecovery

logger = logging.getLogger(__name__)


class RaiseProjectionErrors(TaskiqMiddleware):
    async def post_execute(self, message, result):
        if result.is_err:
            raise result.error or RuntimeError("Projection failed")


class ProjectionReceiver(Receiver):
    def __init__(self, *args, **kwargs):
        # RabbitMQ prefetch=1 limits EACH consumer, not the whole worker.
        # A paused domain must not occupy all execution slots of other domains.
        kwargs["max_async_tasks"] = None
        super().__init__(*args, **kwargs)
        config = get_settings().tasks.projection
        if config is None:
            raise RuntimeError("CQRS is disabled")
        self.config = config
        self.recovery = ProjectionRecovery(config, self.broker)

    async def callback(self, message, raise_err=False):
        if not isinstance(message, AckableMessage):
            raise TypeError(
                "Projection requires acknowledged RabbitMQ messages"
            )
        for attempt in range(self.config.max_retries + 1):
            try:
                decoded = self.broker.formatter.loads(message=message.data)
                expires_at = decoded.labels.get("projection_expires_at")
                if expires_at is not None and float(expires_at) <= time.time():
                    raise ProjectionExpired(
                        "Projection retry deadline has passed"
                    )
                if self.broker.find_task(decoded.task_name) is None:
                    raise ValueError(
                        f"Unknown projection: {decoded.task_name}"
                    )
                # Bytes deliberately leave the real delivery unacknowledged.
                # Taskiq and Dishka finalize a fresh scope per attempt.
                await super().callback(message.data, raise_err=True)
            except ProjectionObsolete:
                logger.info("Skipped superseded or completed projection")
            except Exception as error:
                logger.exception("Projection attempt %s failed", attempt + 1)
                if attempt < self.config.max_retries and not isinstance(
                    error, ProjectionExpired
                ):
                    await asyncio.sleep(self.config.retry_delay)
                    continue
                failure = self.recovery.failure(message.data, error)
                while True:
                    try:
                        await self.recovery.store(failure)
                        break
                    except Exception:
                        # Keep the original unacknowledged while RabbitMQ is
                        # unavailable. Cancellation lets RabbitMQ redeliver it.
                        logger.exception("Could not store projection failure")
                        await asyncio.sleep(self.config.retry_delay)
            await maybe_awaitable(message.ack())
            return
