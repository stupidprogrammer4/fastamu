"""Optional retry middleware for native FastStream RabbitMQ subscribers."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from aio_pika.abc import AbstractIncomingMessage
from faststream import BaseMiddleware
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.schemas.queue import QueueType
from pamqp.commands import Basic

from fastamu.core.config import RetryTransportConfig
from fastamu.messaging.retry import RetryPolicy
from fastamu.tasks.retry import failed_queue, failure_headers, retry_queue

logger = logging.getLogger(__name__)


class EventRetry:
    def __init__(
        self,
        broker: RabbitBroker,
        policies: Mapping[str, RetryPolicy],
        *,
        config: RetryTransportConfig | None = None,
    ):
        self.broker = broker
        self.policies = dict(policies)
        self.config = config or RetryTransportConfig()

    async def replay_failed(
        self, queue: str, *, limit: int | None = None
    ) -> int:
        """Replay only this subscriber's messages, preserving their IDs."""
        limit = self.config.replay_batch_size if limit is None else limit
        if limit < 1:
            raise ValueError("Replay limit must be positive")
        if queue not in self.policies:
            raise ValueError("No retry policy for this queue")
        source = await self.broker.declare_queue(
            RabbitQueue(
                failed_queue(queue, self.config),
                queue_type=QueueType.QUORUM,
                arguments={"x-delivery-limit": -1},
            )
        )
        count = 0
        for _ in range(limit):
            delivery = await source.get(fail=False)
            if delivery is None:
                break
            try:
                if delivery.headers.get("fastamu_queue") != queue:
                    raise ValueError("Failed message belongs to another queue")
                headers = dict(delivery.headers)
                headers.pop("fastamu_attempt", None)
                async with asyncio.timeout(self.config.publish_timeout):
                    confirmation = await self.broker.publish(
                        delivery.body,
                        queue=queue,
                        persist=True,
                        mandatory=True,
                        message_id=delivery.message_id,
                        correlation_id=delivery.correlation_id,
                        content_type=delivery.content_type,
                        content_encoding=delivery.content_encoding,
                        headers=headers,
                    )
                    if not isinstance(confirmation, Basic.Ack):
                        raise RuntimeError("RabbitMQ did not confirm replay")
            except BaseException:
                await delivery.nack(requeue=True)
                raise
            await delivery.ack()
            count += 1
        return count

    def __call__(self, msg, *, context):
        handler = context.get("handler_")
        if msg is None or handler is None:
            return BaseMiddleware(msg, context=context)
        queue = handler.queue.name
        policy = self.policies.get(queue)
        if policy is None:
            return BaseMiddleware(msg, context=context)
        if handler.ack_policy != AckPolicy.MANUAL:
            raise RuntimeError("EventRetry requires AckPolicy.MANUAL")
        return _EventRetry(
            msg,
            context=context,
            broker=self.broker,
            queue=queue,
            policy=policy,
            config=self.config,
        )


class _EventRetry(BaseMiddleware):
    def __init__(self, msg, *, context, broker, queue, policy, config):
        super().__init__(msg, context=context)
        self.delivery: AbstractIncomingMessage = msg
        self.broker = broker
        self.queue = queue
        self.policy = policy
        self.config = config

    async def consume_scope(self, call_next, msg):
        if not self.delivery.message_id:
            raise ValueError("Retryable events require a stable message_id")
        return await call_next(msg)

    async def after_processed(self, exc_type=None, exc_val=None, exc_tb=None):
        if self.delivery.processed:
            return False
        if exc_val is None:
            await self.delivery.ack()
            return False
        if not isinstance(exc_val, Exception):
            await self.delivery.nack(requeue=True)
            return False

        try:
            name, attempt = await self._handoff(exc_val)
        except Exception:
            await asyncio.sleep(self.config.handoff_failure_delay)
            await self.delivery.nack(requeue=True)
            raise
        await self.delivery.ack()
        logger.warning(
            "Event %s attempt %s moved to %s",
            self.delivery.message_id,
            attempt,
            name,
            exc_info=(type(exc_val), exc_val, exc_tb),
        )
        return True

    async def _handoff(self, exc_val):
        previous = self.delivery.headers.get("fastamu_attempt", 0)
        if type(previous) is not int or previous < 0:
            exc_val = ValueError("Invalid event attempt counter")
            previous = 0
        attempt = previous + 1
        headers = failure_headers(
            dict(self.delivery.headers), exc_val, attempt, self.config
        )
        headers.update(
            fastamu_queue=self.queue,
            fastamu_original_exchange=self.delivery.headers.get(
                "fastamu_original_exchange", self.delivery.exchange
            ),
            fastamu_original_routing_key=self.delivery.headers.get(
                "fastamu_original_routing_key", self.delivery.routing_key
            ),
        )
        decision = self.policy.decide(exc_val, attempt)
        arguments: Any
        if decision.delay is not None:
            name, arguments = retry_queue(self.queue, decision, self.config)
        else:
            name, arguments = (
                failed_queue(self.queue, self.config),
                {"x-queue-type": "quorum", "x-delivery-limit": -1},
            )
        async with asyncio.timeout(self.config.publish_timeout):
            await self.broker.declare_queue(
                RabbitQueue(
                    name,
                    queue_type=QueueType.QUORUM,
                    arguments=arguments,
                )
            )
            confirmation = await self.broker.publish(
                self.delivery.body,
                queue=name,
                persist=True,
                mandatory=True,
                message_id=self.delivery.message_id,
                correlation_id=self.delivery.correlation_id,
                content_type=self.delivery.content_type,
                content_encoding=self.delivery.content_encoding,
                headers=headers,
                expiration=decision.delay,
            )
            if not isinstance(confirmation, Basic.Ack):
                raise RuntimeError("RabbitMQ did not confirm event handoff")
        return name, attempt
