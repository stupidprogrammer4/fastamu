"""Keep failed projections durable and retry their original tasks unchanged."""

import base64
import logging
import math
import time
import traceback

from aio_pika import DeliveryMode, Message, connect_robust
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from aiormq.exceptions import ChannelLockedResource
from pamqp.commands import Basic
from pydantic import BaseModel, Field
from taskiq import AsyncBroker, TaskiqMessage

from fastamu.core.config import ProjectionConfig
from fastamu.infra.db.versions import ProjectionExpired

logger = logging.getLogger(__name__)


class ProjectionFailure(BaseModel):
    message: TaskiqMessage | None
    raw_message: str | None = None
    queue: str | None
    attempts: int = Field(ge=1)
    first_failed_at: float
    failed_at: float
    error: str
    last_replay_error: str | None = None
    last_replayed_at: float | None = None
    expires_at: float | None = None
    expired_at: float | None = None


async def publish_confirmed(
    channel: AbstractChannel, queue: str, body: bytes
) -> None:
    confirmation = await channel.default_exchange.publish(
        Message(body=body, delivery_mode=DeliveryMode.PERSISTENT),
        routing_key=queue,
        mandatory=True,
    )
    if not isinstance(confirmation, Basic.Ack):
        raise RuntimeError("RabbitMQ did not confirm projection publication")


class ProjectionRecovery:
    def __init__(self, config: ProjectionConfig, broker: AsyncBroker) -> None:
        self.config = config
        self.broker = broker

    def failure(self, data: bytes, error: Exception) -> ProjectionFailure:
        now = time.time()
        message = None
        raw = None
        queue = None
        try:
            message = self.broker.formatter.loads(data)
        except Exception:
            raw = base64.b64encode(data).decode("ascii")
        if message is not None:
            task = self.broker.find_task(message.task_name)
            labels = task.labels if task is not None else message.labels
            queue = labels.get("queue_name")
        labels = message.labels if message is not None else {}
        try:
            attempts = max(1, int(labels.get("recovery_attempts", 0)) + 1)
            first_failed_at = float(labels.get("first_failed_at", now))
        except (TypeError, ValueError):
            attempts = 1
            first_failed_at = now
        try:
            expires_at = float(
                labels.get(
                    "projection_expires_at",
                    first_failed_at + self.config.retry_ttl,
                )
            )
        except (TypeError, ValueError):
            expires_at = first_failed_at + self.config.retry_ttl
        if not math.isfinite(expires_at) or expires_at <= 0:
            expires_at = now + self.config.retry_ttl
        expired_at = (
            now
            if isinstance(error, ProjectionExpired) or now >= expires_at
            else None
        )
        return ProjectionFailure(
            expires_at=expires_at,
            expired_at=expired_at,
            message=message,
            raw_message=raw,
            queue=queue,
            attempts=attempts,
            first_failed_at=first_failed_at,
            failed_at=now,
            error="".join(traceback.format_exception(error))[-16_384:],
        )

    async def store(self, failure: ProjectionFailure) -> None:
        queue_name = (
            self.config.expired_queue
            if failure.expired_at is not None
            else self.config.failure_queue
        )
        async with await connect_robust(self.config.url) as connection:
            async with connection.channel(
                publisher_confirms=True, on_return_raises=True
            ) as channel:
                await channel.declare_queue(queue_name, durable=True)
                await publish_confirmed(
                    channel,
                    queue_name,
                    failure.model_dump_json().encode(),
                )
        message = failure.message
        logger.error(
            "Stored failed projection task=%s id=%s queue=%s attempts=%s",
            message.task_name if message else None,
            message.task_id if message else None,
            queue_name,
            failure.attempts,
        )

    async def replay(self) -> int:
        """Inspect up to the limit; unresolved work stays for the next tick."""
        replayed = 0
        async with await connect_robust(self.config.url) as connection:
            try:
                async with connection.channel(
                    publisher_confirms=True, on_return_raises=True
                ) as channel:
                    # One scheduler owns the failed queue for this invocation.
                    await channel.declare_queue(
                        self.config.failure_queue + ".lock", exclusive=True
                    )
                    queue = await channel.declare_queue(
                        self.config.failure_queue, durable=True
                    )
                    deliveries: list[AbstractIncomingMessage] = []
                    for _ in range(self.config.recovery_limit):
                        delivery = await queue.get(fail=False)
                        if delivery is None:
                            break
                        deliveries.append(delivery)
                    # Fetch before publishing: a failed replay must not be
                    # picked up again in the same tick, starving other tasks.
                    for delivery in deliveries:
                        try:
                            failure = ProjectionFailure.model_validate_json(
                                delivery.body
                            )
                        except ValueError as error:
                            # Preserve even an invalid envelope for inspection.
                            failure = self.failure(delivery.body, error)
                        deadline = failure.expires_at
                        if deadline is None:
                            deadline = (
                                failure.first_failed_at + self.config.retry_ttl
                            )
                            failure.expires_at = deadline
                        if time.time() >= deadline:
                            failure.expired_at = time.time()
                            await channel.declare_queue(
                                self.config.expired_queue, durable=True
                            )
                            await publish_confirmed(
                                channel,
                                self.config.expired_queue,
                                failure.model_dump_json().encode(),
                            )
                            await delivery.ack()
                            continue
                        try:
                            message = failure.message
                            if message is None:
                                raw = base64.b64decode(
                                    failure.raw_message or "", validate=True
                                )
                                message = self.broker.formatter.loads(raw)
                            message = message.model_copy(deep=True)
                            task = self.broker.find_task(message.task_name)
                            if task is None:
                                raise ValueError(
                                    f"Unknown projection: {message.task_name}"
                                )
                            message.labels["projection_expires_at"] = str(
                                deadline
                            )
                            message.labels["recovery_attempts"] = (
                                failure.attempts
                            )
                            message.labels["first_failed_at"] = (
                                failure.first_failed_at
                            )
                            destination = task.labels["queue_name"]
                            message.labels["queue_name"] = destination
                            body = self.broker.formatter.dumps(message).message
                            await publish_confirmed(channel, destination, body)
                        except Exception as error:
                            failure.last_replay_error = str(error)[-16_384:]
                            failure.last_replayed_at = time.time()
                            # Rotate unresolved tasks to the tail; a removed
                            # task or queue must not block unrelated failures.
                            await publish_confirmed(
                                channel,
                                self.config.failure_queue,
                                failure.model_dump_json().encode(),
                            )
                            logger.warning(
                                "Projection replay deferred task=%s error=%s",
                                failure.message.task_name
                                if failure.message
                                else None,
                                failure.last_replay_error,
                            )
                        else:
                            replayed += 1
                        # ACK only after confirmation. Cancellation or a broken
                        # connection returns all remaining claims to RabbitMQ.
                        await delivery.ack()
            except ChannelLockedResource:
                logger.debug("Another scheduler owns projection recovery")
        logger.info("Requeued %s failed projections", replayed)
        return replayed
