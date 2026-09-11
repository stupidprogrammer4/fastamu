import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from faststream.middlewares.acknowledgement.config import AckPolicy
from pamqp.commands import Basic
from pydantic import ValidationError
from taskiq import AckableMessage, TaskiqMessage
from taskiq.exceptions import SendTaskError
from taskiq.receiver import Receiver

from fastamu.core.config import RetryTransportConfig
from fastamu.core.logger import request_id_ctx
from fastamu.messaging.retry import RetryDecision, RetryPolicy
from fastamu.tasks.events.retry import EventRetry
from fastamu.tasks.projection.broker import ProjectionBroker
from fastamu.tasks.projection.retry import ProjectionRetry
from fastamu.tasks.retry import retry_queue
from fastamu.tasks.schedulers.middlewares.logging import LoggingMiddleware
from fastamu.tasks.schedulers.middlewares.retry import ScheduledRetry


@pytest.mark.parametrize("delays", [(0,), (-1,), (float("nan"),)])
def test_policy_rejects_invalid_delay(delays):
    with pytest.raises(ValidationError):
        RetryPolicy(delays=delays)


def test_retry_queues_confirm_dead_letter_and_have_bounded_jitter():
    policy = RetryPolicy()
    for attempt, base in enumerate(policy.delays, 1):
        name, arguments = retry_queue(
            "source",
            policy.decide(RuntimeError(), attempt),
            RetryTransportConfig(),
        )
        assert name.startswith("fastamu.retry.")
        assert arguments["x-queue-type"] == "quorum"
        assert arguments["x-dead-letter-strategy"] == "at-least-once"
        assert arguments["x-overflow"] == "reject-publish"
        assert arguments["x-dead-letter-routing-key"] == "source"
        assert base <= policy.delay(attempt) <= base * 1.1


@pytest.mark.parametrize(
    "error,total", [(RuntimeError(), 5), (ValueError(), 1)]
)
async def test_taskiq_budget_preserves_id_and_confirms_before_ack(
    error, total
):
    broker = ProjectionBroker("amqp://unused")
    broker.with_middlewares(ProjectionRetry())
    broker.retry_policies["apply"] = RetryPolicy(
        jitter=0, stop_on=(ValueError,)
    )
    trace = []
    broker.kick = AsyncMock(side_effect=lambda _: trace.append("retry"))
    broker.park = AsyncMock(side_effect=lambda *_: trace.append("failed"))

    @broker.task(task_name="apply", queue_name="source")
    async def apply(id):
        trace.append("run")
        raise error

    message = TaskiqMessage(
        task_id="stable",
        task_name="apply",
        labels={"queue_name": "source", "_fastamu_delivery": "delivery-token"},
        args=[42],
        kwargs={},
    )
    receiver = Receiver(broker)
    for attempt in range(1, total + 1):
        ack = AsyncMock(side_effect=lambda: trace.append("ack"))
        await receiver.callback(
            AckableMessage(
                data=broker.formatter.dumps(message).message, ack=ack
            )
        )
        ack.assert_awaited_once()
        if attempt < total:
            encoded = broker.kick.call_args.args[0]
            message = broker.formatter.loads(encoded.message)
            message.parse_labels()
            assert message.task_id == "stable" and message.args == [42]
            assert message.labels["fastamu_attempt"] == attempt
            assert (
                message.labels["fastamu_retry_delay"]
                == (5, 30, 120, 600)[attempt - 1]
            )
    assert trace == ["run", "retry", "ack"] * (total - 1) + [
        "run",
        "failed",
        "ack",
    ]
    assert broker.park.call_args.args[0].labels["fastamu_attempt"] == total


@pytest.mark.parametrize("terminal", [False, True])
async def test_taskiq_handoff_failure_requeues_only_its_delivery(
    terminal,
):
    broker = ProjectionBroker("amqp://unused")
    broker.with_middlewares(ProjectionRetry())
    broker.retry_policies["apply"] = RetryPolicy()
    broker.requeue = AsyncMock()
    broker.retry_policies["apply"] = RetryPolicy(stop_on=(ValueError,))
    broker.kick = AsyncMock(side_effect=ConnectionError("offline"))
    broker.park = AsyncMock(side_effect=ConnectionError("offline"))

    @broker.task(task_name="apply", queue_name="source")
    async def apply():
        raise ValueError() if terminal else RuntimeError()

    message = TaskiqMessage(
        task_id="stable",
        task_name="apply",
        labels={"queue_name": "source", "_fastamu_delivery": "delivery-token"},
        args=[],
        kwargs={},
    )
    ack = AsyncMock()
    with pytest.raises((ConnectionError, SendTaskError)):
        await Receiver(broker).callback(
            AckableMessage(
                data=broker.formatter.dumps(message).message, ack=ack
            )
        )
    ack.assert_not_awaited()
    broker.requeue.assert_awaited_once_with("delivery-token")


async def test_taskiq_cancellation_is_not_a_failed_message():
    broker = ProjectionBroker("amqp://unused")
    broker.with_middlewares(ProjectionRetry())
    broker.retry_policies["apply"] = RetryPolicy()
    broker.park = AsyncMock()

    @broker.task(task_name="apply", queue_name="source")
    async def apply():
        raise asyncio.CancelledError()

    message = TaskiqMessage(
        task_id="stable",
        task_name="apply",
        labels={"queue_name": "source", "_fastamu_delivery": "delivery-token"},
        args=[],
        kwargs={},
    )
    ack = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await Receiver(broker).callback(
            AckableMessage(
                data=broker.formatter.dumps(message).message, ack=ack
            )
        )
    ack.assert_not_awaited()
    broker.park.assert_not_awaited()


@pytest.mark.parametrize(
    "confirmation", [None, False, Basic.Nack(), Basic.Ack()]
)
async def test_event_handoff_confirmation_controls_ack(confirmation):
    broker = SimpleNamespace(
        declare_queue=AsyncMock(), publish=AsyncMock(return_value=confirmation)
    )
    delivery = SimpleNamespace(
        processed=False,
        body=b'{"id":42}',
        headers={},
        message_id="stable",
        correlation_id="correlation",
        content_type="application/json",
        content_encoding=None,
        exchange="events",
        routing_key="changed",
        ack=AsyncMock(),
        nack=AsyncMock(),
    )
    handler = SimpleNamespace(
        queue=SimpleNamespace(name="source"), ack_policy=AckPolicy.MANUAL
    )
    middleware = EventRetry(broker, {"source": RetryPolicy()})(
        delivery, context=SimpleNamespace(get=lambda _: handler)
    )
    if isinstance(confirmation, Basic.Ack):
        assert await middleware.after_processed(RuntimeError, RuntimeError())
        delivery.ack.assert_awaited_once()
        delivery.nack.assert_not_awaited()
    else:
        with pytest.raises(RuntimeError, match="confirm"):
            await middleware.after_processed(RuntimeError, RuntimeError())
        delivery.ack.assert_not_awaited()
        delivery.nack.assert_awaited_once_with(requeue=True)
    assert broker.publish.call_args.kwargs["message_id"] == "stable"
    assert broker.publish.call_args.args[0] == delivery.body


class ApplicationPolicy(RetryPolicy):
    def decide(self, error, attempt):
        # Adapter must not impose an additional error filter or retry budget.
        if isinstance(error, ValueError) and attempt == 11:
            return RetryDecision(delay=0.25, max_delay=0.5)
        return RetryDecision()


async def test_taskiq_uses_custom_policy_as_the_only_decision():
    broker = ProjectionBroker("amqp://unused")
    broker.with_middlewares(ProjectionRetry())
    broker.retry_policies["apply"] = ApplicationPolicy(max_attempts=1)
    broker.kick = AsyncMock()
    broker.park = AsyncMock()

    @broker.task(task_name="apply", queue_name="source")
    async def apply():
        raise ValueError("application says this error is transient")

    message = TaskiqMessage(
        task_id="stable",
        task_name="apply",
        args=[],
        kwargs={},
        labels={"queue_name": "source", "fastamu_attempt": 10},
    )
    await Receiver(broker).callback(broker.formatter.dumps(message).message)
    broker.park.assert_not_awaited()
    encoded = broker.kick.call_args.args[0]
    decoded = broker.formatter.loads(encoded.message)
    decoded.parse_labels()
    assert decoded.labels["fastamu_attempt"] == 11
    assert decoded.labels["fastamu_retry_delay"] == 0.25
    assert decoded.labels["fastamu_retry_max_delay"] == 0.5


async def test_event_uses_custom_policy_and_transport_configuration():
    config = RetryTransportConfig(namespace="project", error_max_length=4)
    broker = SimpleNamespace(
        declare_queue=AsyncMock(), publish=AsyncMock(return_value=Basic.Ack())
    )
    delivery = SimpleNamespace(
        processed=False,
        body=b"{}",
        headers={"fastamu_attempt": 10},
        message_id="stable",
        correlation_id=None,
        content_type=None,
        content_encoding=None,
        exchange="",
        routing_key="source",
        ack=AsyncMock(),
        nack=AsyncMock(),
    )
    handler = SimpleNamespace(
        queue=SimpleNamespace(name="source"), ack_policy=AckPolicy.MANUAL
    )
    middleware = EventRetry(
        broker, {"source": ApplicationPolicy(max_attempts=1)}, config=config
    )(delivery, context=SimpleNamespace(get=lambda _: handler))
    await middleware.after_processed(ValueError, ValueError("transient"))
    published = broker.publish.call_args.kwargs
    assert published["queue"].startswith("project.retry.")
    assert published["expiration"] == 0.25
    assert published["headers"]["fastamu_error"] == "tran"
    assert published["headers"]["fastamu_attempt"] == 11


def test_attempt_budget_is_independent_of_delay_schedule():
    policy = RetryPolicy(max_attempts=7, delays=(1, 2), jitter=0)
    assert [policy.decide(ValueError(), n).delay for n in range(1, 8)] == [
        1,
        2,
        2,
        2,
        2,
        2,
        None,
    ]


async def test_requeue_leaves_other_inflight_deliveries_untouched():
    broker = ProjectionBroker("amqp://unused")
    first = SimpleNamespace(processed=False, nack=AsyncMock())
    second = SimpleNamespace(processed=False, nack=AsyncMock())
    broker._deliveries = {"first": first, "second": second}
    await broker.requeue("first")
    first.nack.assert_awaited_once_with(requeue=True)
    second.nack.assert_not_awaited()
    assert broker._deliveries == {"second": second}


@pytest.mark.parametrize("stored", [True, False])
async def test_scheduled_job_policy_uses_durable_schedule_before_ack(stored):
    source = SimpleNamespace(add_schedule=AsyncMock())
    if not stored:
        source.add_schedule.side_effect = ConnectionError("Redis offline")
    broker = ProjectionBroker("amqp://unused")
    broker.with_middlewares(ScheduledRetry(source, RetryTransportConfig()))
    broker.kick = AsyncMock()

    @broker.task(task_name="job", retry_policy=ApplicationPolicy())
    async def job():
        raise ValueError("transient")

    message = TaskiqMessage(
        task_id="stable",
        task_name="job",
        args=[],
        kwargs={},
        labels={"fastamu_attempt": 10, "retry_policy": "untrusted wire value"},
    )
    ack = AsyncMock()
    delivery = AckableMessage(
        data=broker.formatter.dumps(message).message, ack=ack
    )
    if stored:
        await Receiver(broker).callback(delivery)
        ack.assert_awaited_once()
        scheduled = source.add_schedule.call_args.args[0]
        assert scheduled.task_id == "stable"
        assert scheduled.time is not None
        assert scheduled.labels["fastamu_attempt"] == "11"
        assert "retry_policy" not in scheduled.labels
    else:
        with pytest.raises(ConnectionError):
            await Receiver(broker).callback(delivery)
        ack.assert_not_awaited()
    broker.kick.assert_not_awaited()


async def test_logging_isolated_for_concurrent_duplicate_message_ids():
    middleware = LoggingMiddleware()
    both_started = asyncio.Event()
    started = 0

    async def execute(parent_id):
        nonlocal started
        parent = request_id_ctx.set(parent_id)
        message = TaskiqMessage(
            task_id="duplicate",
            task_name="apply",
            args=[],
            kwargs={},
            labels={},
        )
        try:
            middleware.pre_execute(message)
            started += 1
            if started == 2:
                both_started.set()
            await both_started.wait()
            middleware.post_execute(message, SimpleNamespace(is_err=False))
            assert request_id_ctx.get() == parent_id
        finally:
            request_id_ctx.reset(parent)

    await asyncio.gather(execute("first"), execute("second"))
