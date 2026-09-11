import asyncio
import logging
from functools import partial
from uuid import uuid4

from aio_pika import DeliveryMode, Message
from aiostream import stream
from dishka import make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from pamqp.commands import Basic
from taskiq import AckableMessage, BrokerMessage, TaskiqEvents
from taskiq_aio_pika import AioPikaBroker

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import (
    ProjectionConfig,
    RetryTransportConfig,
    get_settings,
)
from fastamu.core.provider import CoreProvider
from fastamu.messaging.retry import RetryDecision, RetryPolicy
from fastamu.tasks.projection.retry import ProjectionRetry
from fastamu.tasks.retry import failed_queue, failure_headers, retry_queue

logger = logging.getLogger(__name__)


class ProjectionBroker(AioPikaBroker):
    def __init__(self, *args, retry_config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_config = retry_config or RetryTransportConfig()
        self.retry_policies: dict[str, RetryPolicy] = {}
        self._recovery_queues: set[str] = set()
        self._deliveries = {}

    async def requeue(self, token):
        delivery = self._deliveries.pop(token, None)
        if delivery is not None and not delivery.processed:
            await delivery.nack(requeue=True)

    async def _ack(self, token, delivery):
        await delivery.ack()
        self._deliveries.pop(token, None)

    async def _declare_recovery(self, name, arguments):
        if self.write_channel is None:
            raise RuntimeError("Start the projection broker before publishing")
        if name not in self._recovery_queues:
            await self.write_channel.declare_queue(
                name, durable=True, arguments=arguments
            )
            self._recovery_queues.add(name)

    async def park(self, message):
        await self._park_encoded(self.formatter.dumps(message))

    async def _park_encoded(self, message):
        destination = message.labels["queue_name"]
        name = failed_queue(destination, self.retry_config)
        async with asyncio.timeout(self.retry_config.publish_timeout):
            await self._declare_recovery(
                name, {"x-queue-type": "quorum", "x-delivery-limit": -1}
            )
            await self._publish(message, name)

    async def listen(self):
        if self.read_channel is None:
            raise RuntimeError("Start the worker before consuming")
        await self.read_channel.set_qos(prefetch_count=self._qos)
        queues = await self._declare_queues(self.read_channel)
        sources = [_deliveries(queue, args) for queue, args in queues]
        async with stream.merge(*sources).stream() as deliveries:
            async for queue, delivery in deliveries:
                if not self.retry_policies:
                    yield AckableMessage(data=delivery.body, ack=delivery.ack)
                    continue
                decoded = None
                try:
                    decoded = self.formatter.loads(delivery.body)
                    decoded.parse_labels()
                    decoded.labels_types = None
                    if decoded.labels.get("queue_name") != queue:
                        raise ValueError(
                            "Projection destination does not match delivery"
                        )
                    if self.find_task(decoded.task_name) is None:
                        raise ValueError(
                            f"Unknown projection: {decoded.task_name}"
                        )
                    previous = decoded.labels.get("fastamu_attempt", 0)
                    if type(previous) is not int or previous < 0:
                        raise ValueError("Invalid projection attempt counter")
                except Exception as error:
                    invalid = BrokerMessage(
                        task_id=delivery.message_id or str(uuid4()),
                        task_name=decoded.task_name if decoded else "invalid",
                        message=delivery.body,
                        labels=failure_headers(
                            {"queue_name": queue}, error, 0, self.retry_config
                        ),
                    )
                    try:
                        await self._park_encoded(invalid)
                        await delivery.ack()
                    except Exception:
                        logger.exception("Could not park invalid projection")
                        await asyncio.sleep(
                            self.retry_config.handoff_failure_delay
                        )
                        await delivery.nack(requeue=True)
                else:
                    token = uuid4().hex
                    decoded.labels["_fastamu_delivery"] = token
                    self._deliveries[token] = delivery
                    yield AckableMessage(
                        data=self.formatter.dumps(decoded).message,
                        ack=partial(self._ack, token, delivery),
                    )

    async def replay_failed(
        self, queue: str, *, limit: int | None = None
    ) -> int:
        """Replay a bounded batch after repair, preserving task IDs."""
        limit = self.retry_config.replay_batch_size if limit is None else limit
        if limit < 1:
            raise ValueError("Replay limit must be positive")
        if self.write_channel is None:
            raise RuntimeError("Start the projection broker before replaying")
        source = await self.write_channel.get_queue(
            failed_queue(queue, self.retry_config)
        )
        count = 0
        for _ in range(limit):
            delivery = await source.get(fail=False)
            if delivery is None:
                break
            try:
                message = self.formatter.loads(delivery.body)
                if message.labels.get("queue_name") != queue:
                    raise ValueError("Failed message belongs to another queue")
                if self.find_task(message.task_name) is None:
                    raise ValueError("Failed projection is not registered")
                for key in (
                    "fastamu_retry_delay",
                    "fastamu_retry_max_delay",
                    "fastamu_attempt",
                ):
                    message.labels.pop(key, None)
                async with asyncio.timeout(self.retry_config.publish_timeout):
                    await self.kick(self.formatter.dumps(message))
            except BaseException:
                await delivery.nack(requeue=True)
                raise
            await delivery.ack()
            count += 1
        return count

    async def startup(self):
        self._recovery_queues.clear()
        self._deliveries.clear()
        await super().startup()
        if self.read_channel is not None:
            self.read_channel.close_callbacks.add(
                lambda *_: self._deliveries.clear()
            )

    async def kick(self, message: BrokerMessage) -> None:
        if self.write_channel is None:
            raise RuntimeError("Start the projection broker before publishing")
        queue = message.labels.get("queue_name")
        if not isinstance(queue, str) or not queue:
            raise ValueError("Projection destination queue is required")
        if "fastamu_retry_delay" in message.labels:
            decision = RetryDecision(
                delay=float(message.labels["fastamu_retry_delay"]),
                max_delay=float(message.labels["fastamu_retry_max_delay"]),
            )
            name, arguments = retry_queue(queue, decision, self.retry_config)
            async with asyncio.timeout(self.retry_config.publish_timeout):
                await self._declare_recovery(name, arguments)
                await self._publish(message, name, decision.delay)
            return
        await self._publish(message, queue)

    async def _publish(self, message, queue, delay=None):
        if self.write_channel is None:
            raise RuntimeError("Start the projection broker before publishing")
        confirmation = await self.write_channel.default_exchange.publish(
            Message(
                body=message.message,
                message_id=message.task_id,
                delivery_mode=DeliveryMode.PERSISTENT,
                headers={
                    **message.labels,
                    "task_id": message.task_id,
                    "task_name": message.task_name,
                    "queue_name": message.labels.get("queue_name", queue),
                },
                expiration=delay,
            ),
            routing_key=queue,
            mandatory=True,
        )
        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError(
                "RabbitMQ did not confirm projection publication"
            )


async def _deliveries(queue, consumer_args):
    async with queue.iterator(**consumer_args) as messages:
        async for message in messages:
            yield queue.name, message


def create_broker(config: ProjectionConfig) -> ProjectionBroker:
    broker = ProjectionBroker(
        config.url,
        qos=config.prefetch,
        retry_config=config.retry,
    )
    broker.with_middlewares(ProjectionRetry())

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def setup(state):
        container = make_async_container(
            TaskiqProvider(),
            CoreProvider(),
            *get_bootstrapper().boot_providers(),
        )
        setup_dishka(container, broker)
        state.projection_container = container

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def shutdown(state):
        await state.projection_container.close()

    return broker


config = get_settings().tasks.projection
if config is None:
    raise RuntimeError("CQRS is disabled; configure tasks.projection")
broker = create_broker(config)
