"""Retry the current delivery without letting subsequent tasks overtake it.

A delivery that never succeeds is acknowledged and logged rather than
holding the queue, so one document left behind cannot stop the rest.
"""

import asyncio
import logging

from taskiq import AckableMessage, TaskiqMiddleware
from taskiq.receiver import Receiver
from taskiq.utils import maybe_awaitable

from fastamu.core.config import get_settings

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

    async def callback(self, message, raise_err=False):
        if not isinstance(message, AckableMessage):
            raise TypeError(
                "Projection requires acknowledged RabbitMQ messages"
            )
        for attempt in range(self.config.max_retries + 1):
            try:
                decoded = self.broker.formatter.loads(message=message.data)
                if self.broker.find_task(decoded.task_name) is None:
                    raise ValueError(
                        f"Unknown projection: {decoded.task_name}"
                    )
                # Bytes deliberately leave the real delivery unacknowledged.
                # Taskiq and Dishka finalize a fresh scope per attempt.
                await super().callback(message.data, raise_err=True)
            except Exception:
                logger.exception("Projection attempt %s failed", attempt + 1)
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay)
                    continue
                logger.error(
                    "Projection gave up after %s attempts; the queue keeps "
                    "going and this document is left behind",
                    attempt + 1,
                )
            await maybe_awaitable(message.ack())
            return
