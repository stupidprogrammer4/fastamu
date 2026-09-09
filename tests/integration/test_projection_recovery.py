import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from aio_pika import connect_robust
from dishka import make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import AckableMessage, InMemoryBroker, TaskiqMessage
from taskiq.receiver import Receiver

from fastamu.core.config import ProjectionConfig
from fastamu.core.provider import CoreProvider
from fastamu.infra.db.connection import DBConnection
from fastamu.tasks.projection import receiver as receiver_module
from fastamu.tasks.projection import recovery as recovery_module
from fastamu.tasks.projection import worker as worker_module
from fastamu.tasks.projection.receiver import RaiseProjectionErrors
from fastamu.tasks.projection.recovery import (
    ProjectionFailure,
    ProjectionRecovery,
    publish_confirmed,
)
from fastamu.tasks.projection.scheduler import register_recovery


@pytest.fixture
async def runtime(monkeypatch):
    url = os.environ.get("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL for RabbitMQ transport tests")
    name = "test.recovery." + uuid4().hex
    config = ProjectionConfig(
        url=url,
        max_retries=0,
        failure_queue=name + ".failed",
        expired_queue=name + ".expired",
    )
    broker = InMemoryBroker().with_middlewares(RaiseProjectionErrors())
    state = SimpleNamespace(failing=True, written=[])

    @broker.task(task_name="create", queue_name=name)
    async def create(id: int):
        if state.failing:
            raise RuntimeError("Elasticsearch unavailable")
        state.written.append(id)

    @broker.task(task_name="batch", queue_name=name)
    async def batch(ids: list[int]):
        state.written.extend(ids)

    @broker.task(task_name="delete", queue_name=name)
    async def delete(id: int):
        state.written.append(("deleted", id))

    @broker.task(task_name="fanout", queue_name=name)
    async def fanout(id: int):
        state.written.append(("fanout", id))

    recovery = ProjectionRecovery(config, broker)
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    monkeypatch.setattr(receiver_module, "get_settings", lambda: settings)
    receiver = receiver_module.ProjectionReceiver(broker)
    receiver.recovery = recovery

    async with await connect_robust(url) as connection:
        async with connection.channel(
            publisher_confirms=True, on_return_raises=True
        ) as channel:
            queue = await channel.declare_queue(name, durable=True)
            failed = await channel.declare_queue(
                config.failure_queue, durable=True
            )
            expired = await channel.declare_queue(
                config.expired_queue, durable=True
            )
            try:
                yield SimpleNamespace(
                    recovery=recovery,
                    channel=channel,
                    queue=queue,
                    failed=failed,
                    expired=expired,
                    receiver=receiver,
                    state=state,
                )
            finally:
                for item in (queue, failed, expired):
                    await item.delete(if_unused=False, if_empty=False)


def make_failure(runtime, id, name="create", args=None, kwargs=None):
    message = TaskiqMessage(
        task_id=str(id),
        task_name=name,
        args=args if args is not None else [id],
        kwargs=kwargs or {},
        labels={"queue_name": runtime.queue.name},
    )
    return runtime.recovery.failure(
        runtime.recovery.broker.formatter.dumps(message).message,
        RuntimeError("Elasticsearch unavailable"),
    )


async def enqueue_failure(runtime, id, **kwargs):
    failure = make_failure(runtime, id, **kwargs)
    await publish_confirmed(
        runtime.channel,
        runtime.failed.name,
        failure.model_dump_json().encode(),
    )


async def test_failed_delivery_is_stored_before_ack(runtime):
    failure = make_failure(runtime, 1)
    data = runtime.recovery.broker.formatter.dumps(failure.message).message
    await publish_confirmed(runtime.channel, runtime.queue.name, data)
    delivery = await runtime.queue.get()
    await runtime.receiver.callback(
        AckableMessage(data=delivery.body, ack=delivery.ack)
    )
    assert delivery.processed
    stored = await runtime.failed.get()
    value = ProjectionFailure.model_validate_json(stored.body)
    assert value.message.task_id == "1"
    assert value.message.args == [1]
    assert value.attempts == 1
    assert "Elasticsearch unavailable" in value.error
    assert stored.delivery_mode == 2
    await stored.ack()


async def test_scheduler_replays_first_100_without_combining_tasks(runtime):
    for id in range(101):
        await enqueue_failure(runtime, id)
    assert await runtime.recovery.replay() == 100
    runtime.state.failing = False
    for id in range(100):
        delivery = await runtime.queue.get()
        message = runtime.recovery.broker.formatter.loads(delivery.body)
        assert (message.task_name, message.task_id, message.args) == (
            "create",
            str(id),
            [id],
        )
        await runtime.receiver.callback(
            AckableMessage(data=delivery.body, ack=delivery.ack)
        )
    assert runtime.state.written == list(range(100))
    assert await runtime.queue.get(fail=False) is None
    remaining = await runtime.failed.get()
    assert ProjectionFailure.model_validate_json(
        remaining.body
    ).message.args == [100]
    await remaining.ack()


@pytest.mark.parametrize(
    "name,args,kwargs",
    [
        ("create", [1], {}),
        ("batch", [[1, 2]], {}),
        ("delete", [], {"id": 3}),
        ("fanout", [4], {}),
    ],
)
async def test_every_projection_shape_replays_its_original_input(
    runtime, name, args, kwargs
):
    await enqueue_failure(runtime, 1, name=name, args=args, kwargs=kwargs)
    assert await runtime.recovery.replay() == 1
    delivery = await runtime.queue.get()
    message = runtime.recovery.broker.formatter.loads(delivery.body)
    assert (message.task_name, message.args, message.kwargs) == (
        name,
        args,
        kwargs,
    )
    runtime.state.failing = False
    await runtime.receiver.callback(
        AckableMessage(data=delivery.body, ack=delivery.ack)
    )
    assert runtime.state.written


async def test_unroutable_replay_stays_visible_and_succeeds_after_repair(
    runtime,
):
    await enqueue_failure(runtime, 1)
    await runtime.queue.delete()
    assert await runtime.recovery.replay() == 0
    remaining = await runtime.failed.get()
    failure = ProjectionFailure.model_validate_json(remaining.body)
    assert failure.last_replay_error
    assert failure.last_replayed_at is not None
    await remaining.nack(requeue=True)
    await runtime.channel.declare_queue(runtime.queue.name, durable=True)
    assert await runtime.recovery.replay() == 1


async def test_repeated_failures_never_hit_a_terminal_attempt_limit(runtime):
    failure = make_failure(runtime, 1)
    failure.attempts = 1000
    first_failed_at = failure.first_failed_at
    await runtime.recovery.store(failure)
    for expected in (1001, 1002):
        assert await runtime.recovery.replay() == 1
        delivery = await runtime.queue.get()
        await runtime.receiver.callback(
            AckableMessage(data=delivery.body, ack=delivery.ack)
        )
        stored = await runtime.failed.get()
        failure = ProjectionFailure.model_validate_json(stored.body)
        assert failure.attempts == expected
        assert failure.first_failed_at == first_failed_at
        assert failure.message.task_id == "1"
        await stored.nack(requeue=True)
    runtime.state.failing = False
    assert await runtime.recovery.replay() == 1
    delivery = await runtime.queue.get()
    await runtime.receiver.callback(
        AckableMessage(data=delivery.body, ack=delivery.ack)
    )
    assert runtime.state.written == [1]
    assert await runtime.failed.get(fail=False) is None


async def test_unknown_task_does_not_block_others_and_recovers_when_registered(
    runtime,
):
    await enqueue_failure(runtime, 1, name="missing")
    await enqueue_failure(runtime, 2)
    assert await runtime.recovery.replay() == 1
    stored = await runtime.failed.get()
    failure = ProjectionFailure.model_validate_json(stored.body)
    assert "Unknown projection" in failure.last_replay_error
    await stored.nack(requeue=True)

    @runtime.recovery.broker.task(
        task_name="missing", queue_name=runtime.queue.name
    )
    async def missing(id: int):
        pass

    assert await runtime.recovery.replay() == 1
    first = await runtime.queue.get()
    second = await runtime.queue.get()
    assert (
        runtime.recovery.broker.formatter.loads(first.body).task_name
        == "create"
    )
    assert (
        runtime.recovery.broker.formatter.loads(second.body).task_name
        == "missing"
    )
    await first.ack()
    await second.ack()


async def test_malformed_payload_remains_visible_without_blocking_others(
    runtime,
):
    await publish_confirmed(runtime.channel, runtime.failed.name, b"broken")
    await enqueue_failure(runtime, 2)
    assert await runtime.recovery.replay() == 1
    stored = await runtime.failed.get()
    failure = ProjectionFailure.model_validate_json(stored.body)
    assert failure.raw_message == "YnJva2Vu"
    assert failure.last_replay_error
    await stored.ack()


async def test_overlapping_schedulers_do_not_steal_claimed_messages(
    runtime, monkeypatch
):
    await enqueue_failure(runtime, 1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def paused(channel, queue, body):
        if queue == runtime.queue.name:
            entered.set()
            await release.wait()
        await publish_confirmed(channel, queue, body)

    monkeypatch.setattr(recovery_module, "publish_confirmed", paused)
    first = asyncio.create_task(runtime.recovery.replay())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await runtime.recovery.replay() == 0
        release.set()
        assert await first == 1
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


async def test_cancelled_scheduler_returns_its_unacked_failures(
    runtime, monkeypatch
):
    await enqueue_failure(runtime, 1)
    entered = asyncio.Event()

    async def interrupted(channel, queue, body):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(recovery_module, "publish_confirmed", interrupted)
    task = asyncio.create_task(runtime.recovery.replay())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    remaining = await runtime.failed.get()
    assert remaining.redelivered
    await remaining.ack()
    assert await runtime.queue.get(fail=False) is None


async def test_failed_republication_cannot_ack_the_original(
    runtime, monkeypatch
):
    await enqueue_failure(runtime, 1)

    async def unavailable(channel, queue, body):
        raise ConnectionError("RabbitMQ unavailable")

    monkeypatch.setattr(recovery_module, "publish_confirmed", unavailable)
    with pytest.raises(ConnectionError):
        await runtime.recovery.replay()
    remaining = await runtime.failed.get()
    assert remaining.redelivered
    await remaining.ack()


@pytest.mark.parametrize("queued", [False, True])
async def test_scheduler_never_resolves_database_even_when_replaying(
    runtime, monkeypatch, queued
):
    database = Mock(side_effect=AssertionError("Scheduler requested database"))
    monkeypatch.setattr(DBConnection, "__init__", database)
    monkeypatch.setattr(
        worker_module, "get_broker", lambda: runtime.recovery.broker
    )
    broker = InMemoryBroker().with_middlewares(RaiseProjectionErrors())
    container = make_async_container(TaskiqProvider(), CoreProvider())
    setup_dishka(container, broker)
    register_recovery(broker, runtime.recovery.config)
    receiver = Receiver(broker)
    if queued:
        await enqueue_failure(runtime, 1)
    try:
        for tick in range(2):
            message = TaskiqMessage(
                task_id=str(tick),
                task_name="fastamu.projection.recover",
                args=[],
                kwargs={},
                labels={},
            )
            await receiver.callback(
                broker.formatter.dumps(message).message, raise_err=True
            )
        database.assert_not_called()
        assert runtime.state.written == []
        delivery = await runtime.queue.get(fail=False)
        assert (delivery is not None) == queued
        if delivery is not None:
            await delivery.ack()
    finally:
        await container.close()


async def test_worker_disconnect_redelivers_unacknowledged_projection(runtime):
    entered = asyncio.Event()

    @runtime.recovery.broker.task(
        task_name="interrupted", queue_name=runtime.queue.name
    )
    async def interrupted(id: int):
        entered.set()
        await asyncio.Event().wait()

    message = make_failure(runtime, 1, name="interrupted").message
    body = runtime.recovery.broker.formatter.dumps(message).message
    await publish_confirmed(runtime.channel, runtime.queue.name, body)
    async with await connect_robust(runtime.recovery.config.url) as connection:
        async with connection.channel() as channel:
            queue = await channel.get_queue(runtime.queue.name)
            delivery = await queue.get()
            running = asyncio.create_task(
                runtime.receiver.callback(
                    AckableMessage(data=delivery.body, ack=delivery.ack)
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), 5)
            finally:
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
    redelivered = await runtime.queue.get()
    assert redelivered.redelivered
    assert redelivered.body == body
    await redelivered.ack()


async def test_expired_failure_is_archived_without_replaying(runtime):
    failure = make_failure(runtime, 7)
    failure.expires_at = time.time() - 1
    await publish_confirmed(
        runtime.channel,
        runtime.failed.name,
        failure.model_dump_json().encode(),
    )
    assert await runtime.recovery.replay() == 0
    assert await runtime.queue.get(fail=False) is None
    assert await runtime.failed.get(fail=False) is None
    archived = await runtime.expired.get()
    saved = ProjectionFailure.model_validate_json(archived.body)
    assert saved.message.task_id == failure.message.task_id
    assert saved.expired_at is not None
    assert saved.expires_at == failure.expires_at
    await archived.ack()


async def test_worker_archives_expired_delivery_before_execution(runtime):
    message = make_failure(runtime, 7).message
    message.labels["projection_expires_at"] = str(time.time() - 1)
    body = runtime.recovery.broker.formatter.dumps(message).message
    await publish_confirmed(runtime.channel, runtime.queue.name, body)
    delivery = await runtime.queue.get()
    await runtime.receiver.callback(
        AckableMessage(data=delivery.body, ack=delivery.ack)
    )
    assert runtime.state.written == []
    assert await runtime.failed.get(fail=False) is None
    archived = await runtime.expired.get()
    saved = ProjectionFailure.model_validate_json(archived.body)
    assert saved.message.task_id == message.task_id
    assert saved.expired_at is not None
    await archived.ack()
