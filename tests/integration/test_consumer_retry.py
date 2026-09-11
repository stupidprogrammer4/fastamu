import asyncio
import os
import time
from typing import Any
from uuid import uuid4

import pytest
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitQueue, RabbitRouter
from faststream.rabbit.schemas.queue import QueueType
from redis.asyncio import Redis
from taskiq import TaskiqMessage, TaskiqScheduler
from taskiq.receiver import Receiver
from taskiq_aio_pika import Queue
from taskiq_redis import RedisScheduleSource, RedisStreamBroker

from fastamu.core.config import EventsConfig, RetryTransportConfig
from fastamu.messaging.retry import RetryPolicy
from fastamu.tasks.events.factory import BrokerFactory
from fastamu.tasks.events.retry import EventRetry
from fastamu.tasks.projection.broker import ProjectionBroker
from fastamu.tasks.projection.retry import ProjectionRetry
from fastamu.tasks.retry import failed_queue, retry_queue
from fastamu.tasks.schedulers.middlewares.retry import ScheduledRetry


@pytest.fixture
def url():
    value = os.getenv("FASTAMU_RABBIT_TEST_URL")
    if not value:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL")
    return value


async def get_message(channel, name, timeout=10):
    async with asyncio.timeout(timeout):
        while True:
            queue = await channel.get_queue(name, ensure=False)
            message = await queue.get(fail=False)
            if message is not None:
                return message
            await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "outcome", ["success", "failed", "permanent", "handoff"]
)
async def test_taskiq_real_retry_and_failed_queue(url, outcome, monkeypatch):
    name = "test.retry." + uuid4().hex
    policy = RetryPolicy(
        max_attempts=3, delays=(0.1, 0.2), jitter=0, stop_on=(ValueError,)
    )
    broker = ProjectionBroker(url, task_queues=[Queue(name=name)], qos=1)
    broker.with_middlewares(ProjectionRetry())
    broker.retry_policies["apply"] = policy
    broker.is_worker_process = True
    runs = []
    repaired = False
    replayed = asyncio.Event()

    @broker.task(task_name="apply", queue_name=name)
    async def apply(id: Any):
        runs.append((id, time.monotonic()))
        if repaired:
            replayed.set()
            return
        if outcome == "permanent":
            raise ValueError("invalid payload")
        if outcome in ("failed", "handoff") or len(runs) < 3:
            raise RuntimeError("temporary")

    await broker.startup()
    receiver = Receiver(broker)
    deliveries = []
    errors = []
    done = asyncio.Event()

    async def process(message):
        try:
            await receiver.callback(message)
            decoded = broker.formatter.loads(message.data)
            if (
                int(decoded.labels.get("fastamu_attempt", 0)) == 2
                or outcome == "permanent"
            ):
                done.set()
        except Exception as error:
            errors.append(error)

    async def listen():
        async for message in broker.listen():
            deliveries.append(asyncio.create_task(process(message)))

    if outcome == "handoff":
        publish = broker._publish
        failed = False

        async def unavailable_once(message, queue, delay=None):
            nonlocal failed
            if queue != name and not failed:
                failed = True
                raise ConnectionError("handoff unavailable")
            return await publish(message, queue, delay)

        monkeypatch.setattr(broker, "_publish", unavailable_once)
    listener = asyncio.create_task(listen())
    try:
        await apply.kicker().with_task_id("stable").kiq(42)
        await asyncio.wait_for(done.wait(), 12)
        await asyncio.gather(*deliveries)
        expected = (
            1 if outcome == "permanent" else 4 if outcome == "handoff" else 3
        )
        assert len(runs) == expected
        assert all(id == 42 for id, _ in runs)
        assert bool(errors) is (outcome == "handoff")
        if outcome != "success":
            failed = await get_message(
                broker.write_channel, failed_queue(name, broker.retry_config)
            )
            decoded = broker.formatter.loads(failed.body)
            assert failed.message_id == decoded.task_id == "stable"
            assert decoded.args == [42]
            assert int(decoded.labels["fastamu_attempt"]) == (
                1 if outcome == "permanent" else 3
            )
            await failed.nack(requeue=True)
            repaired = True
            assert await broker.replay_failed(name, limit=1) == 1
            await asyncio.wait_for(replayed.wait(), 5)
            await asyncio.gather(*deliveries)
            assert len(runs) == expected + 1
        if outcome == "success":
            assert runs[1][1] - runs[0][1] >= 0.08
            assert runs[2][1] - runs[1][1] >= 0.18
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
        for task in deliveries:
            task.cancel()
        await asyncio.gather(*deliveries, return_exceptions=True)
        for queue_name in {name, *broker._recovery_queues}:
            queue = await broker.write_channel.get_queue(
                queue_name, ensure=False
            )
            await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()


async def test_retry_waits_for_missing_destination_without_losing_message(url):
    name = "test.retry." + uuid4().hex
    policy = RetryPolicy(delays=(0.1,), jitter=0)
    broker = ProjectionBroker(url, task_queues=[Queue(name=name)])
    broker.retry_policies["apply"] = policy
    await broker.startup()
    try:
        source = await broker.write_channel.get_queue(name)
        await source.delete(if_unused=False, if_empty=False)
        message = TaskiqMessage(
            task_id="stable",
            task_name="apply",
            args=[42],
            kwargs={},
            labels={
                "queue_name": name,
                "fastamu_attempt": 1,
                "fastamu_retry_delay": 0.1,
                "fastamu_retry_max_delay": 0.1,
            },
        )
        await broker.kick(broker.formatter.dumps(message))
        await asyncio.sleep(0.3)
        await broker._declare_queues(broker.write_channel)
        received = await get_message(broker.write_channel, name, timeout=200)
        assert received.message_id == "stable"
        await received.ack()
    finally:
        for queue_name in {name, *broker._recovery_queues}:
            queue = await broker.write_channel.get_queue(
                queue_name, ensure=False
            )
            await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()


@pytest.mark.parametrize("permanent", [False, True])
async def test_faststream_native_router_retry_and_failure(url, permanent):
    name = "test.event.retry." + uuid4().hex
    policy = RetryPolicy(
        max_attempts=3, delays=(0.1, 0.2), jitter=0, stop_on=(ValueError,)
    )
    broker = BrokerFactory.create(EventsConfig(broker="rabbitmq", url=url))
    retry = EventRetry(broker, {name: policy})
    router = RabbitRouter(
        middlewares=[retry],
        ack_policy=AckPolicy.MANUAL,
    )
    runs = []
    repaired = False
    replayed = asyncio.Event()

    @router.subscriber(RabbitQueue(name, durable=True))
    async def handle(data: dict):
        runs.append(data)
        if repaired:
            replayed.set()
            return
        raise ValueError("invalid") if permanent else RuntimeError("temporary")

    broker.include_router(router)
    await broker.start()
    inspector = ProjectionBroker(
        url, task_queues=[Queue(name=name + ".inspect")]
    )
    await inspector.startup()
    try:
        await broker.publish(
            {"id": 42}, queue=name, message_id="stable", persist=True
        )
        # The failed destination is declared on terminal failure.
        async with asyncio.timeout(10):
            while len(runs) < (1 if permanent else 3):
                await asyncio.sleep(0.02)
        # Declaration through the same public API is idempotent.

        await broker.declare_queue(
            RabbitQueue(
                failed_queue(name, retry.config),
                queue_type=QueueType.QUORUM,
                arguments={"x-delivery-limit": -1},
            )
        )
        message = await get_message(
            inspector.write_channel, failed_queue(name, retry.config)
        )
        assert message.message_id == "stable"
        assert message.headers["fastamu_attempt"] == (1 if permanent else 3)
        assert message.headers["fastamu_queue"] == name
        assert runs == [{"id": 42}] * (1 if permanent else 3)
        await message.nack(requeue=True)
        repaired = True
        assert await retry.replay_failed(name, limit=1) == 1
        await asyncio.wait_for(replayed.wait(), 5)
    finally:
        await broker.stop()
        queues = {name, name + ".inspect", failed_queue(name, retry.config)}
        if not permanent:
            queues.update(
                retry_queue(
                    name, policy.decide(RuntimeError(), n), retry.config
                )[0]
                for n in (1, 2)
            )
        for queue_name in queues:
            queue = await inspector.write_channel.get_queue(
                queue_name, ensure=False
            )
            await queue.delete(if_unused=False, if_empty=False)
        await inspector.shutdown()


@pytest.mark.parametrize("fault", ["malformed", "unknown", "counter"])
async def test_invalid_projection_is_parked_without_stalling_worker(
    url, fault
):
    name = "test.invalid." + uuid4().hex
    broker = ProjectionBroker(url, task_queues=[Queue(name=name)])
    broker.retry_policies["apply"] = RetryPolicy()
    broker.is_worker_process = True

    @broker.task(task_name="apply", queue_name=name)
    async def apply():
        pass

    await broker.startup()
    listener = broker.listen()
    pending = asyncio.create_task(anext(listener))
    message = TaskiqMessage(
        task_id="invalid-id",
        task_name="unknown" if fault == "unknown" else "apply",
        args=[],
        kwargs={},
        labels={
            "queue_name": name,
            "fastamu_attempt": -1 if fault == "counter" else 0,
        },
    )
    encoded = broker.formatter.dumps(message)
    if fault == "malformed":
        encoded.message = b"not-json"
    try:
        await broker.kick(encoded)
        destination = failed_queue(name, broker.retry_config)
        # Declare before basic.get so the test never closes a channel with 404.
        await broker._declare_recovery(
            destination, {"x-queue-type": "quorum", "x-delivery-limit": -1}
        )
        failed = await get_message(broker.write_channel, destination)
        assert failed.message_id == "invalid-id"
        assert failed.body == encoded.message
        await failed.nack(requeue=True)
        if fault == "unknown":
            with pytest.raises(ValueError, match="registered"):
                await broker.replay_failed(name, limit=1)
            retained = await get_message(broker.write_channel, destination)
            assert retained.message_id == "invalid-id"
            await retained.ack()
        await apply.kiq()
        valid = await asyncio.wait_for(pending, 5)
        assert broker.formatter.loads(valid.data).task_name == "apply"
        await Receiver(broker).callback(valid)
        assert not broker._deliveries
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await listener.aclose()
        for queue_name in {name, *broker._recovery_queues}:
            queue = await broker.write_channel.get_queue(
                queue_name, ensure=False
            )
            await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()


async def test_redis_job_retry_is_scheduled_and_preserves_task_id():
    url = os.getenv("FASTAMU_REDIS_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_REDIS_TEST_URL")
    name = "test.retry." + uuid4().hex
    source = RedisScheduleSource(url, prefix=name + ".schedule")
    broker = RedisStreamBroker(url, queue_name=name, consumer_group_name=name)
    broker.with_middlewares(ScheduledRetry(source, RetryTransportConfig()))
    runs = []

    @broker.task(
        task_name="job", retry_policy=RetryPolicy(delays=(0.1,), jitter=0)
    )
    async def job():
        runs.append(True)
        if len(runs) == 1:
            raise RuntimeError("temporary")

    await broker.startup()
    listener = broker.listen()
    receiver = Receiver(broker)
    try:
        await job.kicker().with_task_id("stable").kiq()
        message = await asyncio.wait_for(anext(listener), 5)
        await receiver.callback(message)
        schedules = await source.get_schedules()
        assert len(schedules) == 1
        scheduled = schedules[0]
        assert scheduled.task_id == "stable"
        assert runs == [True]
        # Invoke the native scheduler delivery hook after the due time.
        await asyncio.sleep(0.12)
        await TaskiqScheduler(broker, [source]).on_ready(source, scheduled)
        assert await source.get_schedules() == []
        retry = await asyncio.wait_for(anext(listener), 5)
        decoded = broker.formatter.loads(retry.data)
        assert decoded.task_id == "stable"
        await receiver.callback(retry)
        assert len(runs) == 2
    finally:
        await listener.aclose()
        for scheduled in await source.get_schedules():
            await source.delete_schedule(scheduled.schedule_id)
        async with Redis.from_url(url) as client:
            await client.delete(name)
        await broker.shutdown()
