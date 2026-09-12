"""Recording terminal failures and repairing them on a periodic run."""

import asyncio
import logging
from collections.abc import Sequence
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import InMemoryBroker, TaskiqMessage, TaskiqScheduler
from taskiq.acks import AckableMessage
from taskiq.middlewares import SmartRetryMiddleware

from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
    AbstractUnProjection,
)
from fastamu.messaging.projections.contracts.policies import RetryPolicy
from fastamu.messaging.projections.contracts.results import BulkItemResult
from fastamu.messaging.projections.repair.orchestration import Repair
from fastamu.tasks.projection.delivery.register import Register
from fastamu.tasks.projection.delivery.retry import RetryLabelsMiddleware
from fastamu.tasks.projection.repair import targets
from fastamu.tasks.projection.repair.failures import (
    ProjectionFailureMiddleware,
)
from tests.unit.test_projection_failure_queue import make_queue
from tests.unit.test_projection_retry import Schedules


@pytest.fixture
def queue():
    store, _ = make_queue()
    return store


async def repair_of(
    projections: Sequence[type],
    store,
    batch_size: int = 1000,
) -> tuple[Repair, Register, InMemoryBroker, object]:
    """Register projections, then repair them through their own classes."""
    broker = InMemoryBroker(await_inplace=True)
    register = Register()
    for projection in projections:
        register.register(projection, broker)
    names = [register.get(projection).task_name for projection in projections]
    provider = Provider()
    provider.provide_all(*projections, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    resolved = targets.resolve(register, {name: name for name in names})
    repair = Repair(store, targets.runners(resolved, container), batch_size)
    return repair, register, broker, container


class Broken(AbstractUnProjection):
    queue_name: ClassVar[str] = "products"
    retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(max_attempts=2)

    async def _es_query(self, id: int) -> None:
        raise ValueError("projection failed")


async def test_1000_failures_across_50_projections_run_50_batches(
    queue,
) -> None:
    writes: dict[str, list[int]] = {}

    class Batch(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            writes[type(self).__name__] = list(ids)
            return [BulkItemResult(id=str(id), status=200) for id in ids]

    classes = [
        type(f"Batch{i}", (Batch,), {"__module__": __name__})
        for i in range(50)
    ]
    repair, register, broker, container = await repair_of(classes, queue)
    names = [register.get(cls).task_name for cls in classes]
    for index, name in enumerate(names):
        await queue.record(
            name, list(range(index * 20, (index + 1) * 20)), "fail"
        )
    await broker.startup()
    try:
        assert await repair.run() == 1000
        assert len(writes) == 50
        for i in range(50):
            assert sorted(writes[f"Batch{i}"]) == list(
                range(i * 20, (i + 1) * 20)
            )
        for name in names:
            assert await queue.take(name, 10) == []
    finally:
        await broker.shutdown()
        await container.close()


async def test_native_retry_records_only_the_terminal_failure(queue) -> None:
    source = Schedules()
    broker = InMemoryBroker(await_inplace=True)
    task = Register().register(Broken, broker)
    broker.with_middlewares(
        ProjectionFailureMiddleware(queue, [task.task_name]),
        RetryLabelsMiddleware(),
        SmartRetryMiddleware(schedule_source=source),
    )
    provider = Provider()
    provider.provide(Broken, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    await broker.startup()
    try:
        sent = await task.kiq(id=7)
        assert await queue.take(task.task_name, 10) == []
        assert len(source.pending) == 1
        await TaskiqScheduler(broker, [source]).on_ready(
            source, source.pending[0]
        )
        assert isinstance((await sent.wait_result()).error, ValueError)
        records = await queue.take(task.task_name, 10)
        assert [record.input_id for record in records] == [7]
        assert records[0].error == "projection failed"
    finally:
        await broker.shutdown()
        await container.close()


async def test_a_partial_batch_failure_records_only_what_it_left(
    queue,
) -> None:
    class PartialBatch(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            return [
                BulkItemResult(id=str(id), status=500 if id == 8 else 200)
                for id in ids
            ]

    broker = InMemoryBroker(await_inplace=True)
    task = Register().register(PartialBatch, broker)
    broker.with_middlewares(
        ProjectionFailureMiddleware(queue, [task.task_name])
    )
    provider = Provider()
    provider.provide(PartialBatch, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    await broker.startup()
    try:
        assert (await (await task.kiq(ids=[7, 8])).wait_result()).is_err
        records = await queue.take(task.task_name, 10)
        assert [record.input_id for record in records] == [8]
    finally:
        await broker.shutdown()
        await container.close()


async def test_a_final_item_is_not_recorded_as_a_failure(queue) -> None:
    class Conflicting(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            return [
                BulkItemResult(
                    id=str(id),
                    status=409,
                    error={"type": "version_conflict_engine_exception"},
                    final=True,
                )
                for id in ids
            ]

    broker = InMemoryBroker(await_inplace=True)
    task = Register().register(Conflicting, broker)
    broker.with_middlewares(
        ProjectionFailureMiddleware(queue, [task.task_name])
    )
    provider = Provider()
    provider.provide(Conflicting, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    await broker.startup()
    try:
        assert not (await (await task.kiq(ids=[7, 8])).wait_result()).is_err
        assert await queue.take(task.task_name, 10) == []
    finally:
        await broker.shutdown()
        await container.close()


async def test_an_unsettled_repair_is_handed_back_and_then_given_up(
    caplog,
) -> None:
    """A 404 is an error like any other: retried, then abandoned visibly."""
    store, fake = make_queue(max_attempts=2)
    calls: list[list[int]] = []

    class Missing(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            calls.append(list(ids))
            return [BulkItemResult(id=str(id), status=404) for id in ids]

    repair, register, broker, container = await repair_of([Missing], store)
    name = register.get(Missing).task_name
    await store.record(name, [7], "source is gone")
    await broker.startup()
    try:
        with caplog.at_level(logging.WARNING):
            assert await repair.run() == 0
            assert await repair.run() == 0
            assert await repair.run() == 0
        assert calls == [[7], [7]]
        assert "Gave up on 1" in caplog.text
        assert fake.lists[store.dead_key(name)]
    finally:
        await broker.shutdown()
        await container.close()


async def test_a_failing_repair_run_hands_its_whole_batch_back(queue) -> None:
    class Exploding(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            raise ConnectionError("Elasticsearch down")

    repair, register, broker, container = await repair_of([Exploding], queue)
    name = register.get(Exploding).task_name
    await queue.record(name, [7, 8], "failed")
    await broker.startup()
    try:
        assert await repair.run() == 0
        records = await queue.take(name, 10)
        assert [record.input_id for record in records] == [7, 8]
        assert [record.attempts for record in records] == [1, 1]
    finally:
        await broker.shutdown()
        await container.close()


async def test_projections_repair_concurrently_up_to_the_limit(
    queue,
) -> None:
    """Two groups meet inside the same tick; the third waits for a slot."""
    pairs = asyncio.Barrier(2)

    class Paired(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            await pairs.wait()
            return [BulkItemResult(id=str(id), status=200) for id in ids]

    classes = [
        type(f"Paired{i}", (Paired,), {"__module__": __name__})
        for i in range(4)
    ]
    repair, register, broker, container = await repair_of(classes, queue)
    repair.concurrency = 2
    for cls in classes:
        await queue.record(register.get(cls).task_name, [7], "failed")
    await broker.startup()
    try:
        assert await asyncio.wait_for(repair.run(), 5) == 4
    finally:
        await broker.shutdown()
        await container.close()


async def test_one_unreachable_queue_does_not_abandon_the_others(
    queue,
    caplog,
) -> None:
    class Batch(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"

        async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
            return [BulkItemResult(id=str(id), status=200) for id in ids]

    first = type("First", (Batch,), {"__module__": __name__})
    second = type("Second", (Batch,), {"__module__": __name__})
    repair, register, broker, container = await repair_of(
        [first, second], queue
    )
    broken = register.get(first).task_name
    working = register.get(second).task_name
    await queue.record(working, [7, 8], "failed")
    take = queue.take

    async def fail_one(name: str, limit: int):
        if name == broken:
            raise ConnectionError("Redis down")
        return await take(name, limit)

    queue.take = fail_one
    await broker.startup()
    try:
        with caplog.at_level(logging.ERROR):
            assert await repair.run() == 2
        assert f"Could not repair projection: {broken}" in caplog.text
    finally:
        await broker.shutdown()
        await container.close()


async def test_storage_failure_is_not_acknowledged(queue, monkeypatch) -> None:
    broker = InMemoryBroker(await_inplace=True)
    task = Register().register(Broken, broker)
    broker.with_middlewares(
        ProjectionFailureMiddleware(queue, [task.task_name])
    )
    provider = Provider()
    provider.provide(Broken, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    monkeypatch.setattr(
        queue, "record", AsyncMock(side_effect=ConnectionError("Redis down"))
    )
    ack = AsyncMock()
    message = TaskiqMessage(
        task_id="store-down",
        task_name=task.task_name,
        labels=task.labels,
        args=[],
        kwargs={"id": 7},
    )
    await broker.startup()
    try:
        with pytest.raises(ConnectionError, match="Redis down"):
            await broker.receiver.callback(
                AckableMessage(
                    data=broker.formatter.dumps(message).message,
                    ack=ack,
                )
            )
        ack.assert_not_awaited()
    finally:
        await broker.shutdown()
        await container.close()


def test_invalid_mappings_fail_before_anything_runs() -> None:
    register = Register()
    task = register.register(Broken, InMemoryBroker())
    with pytest.raises(ValueError, match="Unknown repair mapping"):
        targets.resolve(register, {task.task_name: "missing"})
    with pytest.raises(TypeError, match="must be a batch"):
        targets.resolve(register, {task.task_name: task.task_name})
