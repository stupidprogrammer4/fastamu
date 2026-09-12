from collections.abc import Sequence
from datetime import datetime, timezone
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from pydantic import ValidationError
from taskiq import (
    InMemoryBroker,
    ScheduledTask,
    ScheduleSource,
    TaskiqMessage,
    TaskiqMiddleware,
    TaskiqScheduler,
)
from taskiq.acks import AckableMessage
from taskiq.middlewares import SmartRetryMiddleware

from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
)
from fastamu.messaging.projections.contracts.policies import RetryPolicy
from fastamu.messaging.projections.contracts.results import BulkItemResult
from fastamu.tasks.projection.delivery.register import Register
from fastamu.tasks.projection.delivery.retry import (
    RetryLabelsMiddleware,
)
from tests.unit.test_projection_register import DeleteProduct, Resources, Trace


class Schedules(ScheduleSource):
    def __init__(self) -> None:
        self.pending: list[ScheduledTask] = []

    async def get_schedules(self) -> list[ScheduledTask]:
        return self.pending.copy()

    async def add_schedule(self, schedule: ScheduledTask) -> None:
        self.pending.append(schedule)

    async def post_send(self, task: ScheduledTask) -> None:
        self.pending.remove(task)


class Publications(TaskiqMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[TaskiqMessage] = []

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        self.messages.append(message.model_copy(deep=True))
        return message


@pytest.mark.parametrize("attempts", [1, 2, 4])
async def test_native_retry_counts_routes_and_closes_each_scope(
    attempts: int,
) -> None:
    class RetryProduct(DeleteProduct):
        retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
            max_attempts=attempts,
            delay=7,
        )

    class RetryVariant(DeleteProduct):
        queue_name: ClassVar[str] = "variants"
        retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
            max_attempts=2,
            delay=19,
        )

    source = Schedules()
    publications = Publications()
    broker = InMemoryBroker(await_inplace=True).with_middlewares(
        RetryLabelsMiddleware(),
        publications,
        SmartRetryMiddleware(schedule_source=source),
    )
    trace = Trace()
    provider = Resources()
    provider.provide(lambda: trace, provides=Trace, scope=Scope.APP)
    provider.provide_all(
        RetryProduct,
        RetryVariant,
        DeleteProduct,
        scope=Scope.REQUEST,
    )
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    registry = Register()
    for projection in (RetryProduct, RetryVariant, DeleteProduct):
        registry.register(projection, broker)
    scheduler = TaskiqScheduler(broker, [source])
    await broker.startup()
    try:
        before = datetime.now(timezone.utc)
        product = await registry.get(RetryProduct).kiq(id=-1)
        variant = await registry.get(RetryVariant).kiq(id=-2)
        disabled = await registry.get(DeleteProduct).kiq(id=-3)
        success = await registry.get(RetryProduct).kiq(id=4)
        assert len(source.pending) == (1 if attempts == 1 else 2)
        assert len(trace.closed) == 4
        for schedule in source.pending:
            delay = 7 if schedule.task_id == product.task_id else 19
            assert schedule.time is not None
            assert (schedule.time - before).total_seconds() >= delay
            assert "dishka_container_id" not in schedule.labels
        # Dispatch deterministically; real timing is tested with Redis.
        while source.pending:
            await scheduler.on_ready(source, source.pending[0])

        counts = {
            id: sum(message.task_id == id for message in publications.messages)
            for id in (
                product.task_id,
                variant.task_id,
                disabled.task_id,
                success.task_id,
            )
        }
        assert counts == {
            product.task_id: attempts,
            variant.task_id: 2,
            disabled.task_id: 1,
            success.task_id: 1,
        }
        for message in publications.messages:
            assert "delay" not in message.labels
            assert message.labels["queue_name"] == (
                "variants"
                if message.task_id == variant.task_id
                else "products"
            )
        assert trace.opened == trace.closed == list(range(attempts + 4))
        assert isinstance((await product.wait_result()).error, LookupError)
        assert isinstance((await variant.wait_result()).error, LookupError)
        assert isinstance((await disabled.wait_result()).error, LookupError)
        assert not (await success.wait_result()).is_err
        assert registry.get(RetryProduct).labels["max_retries"] == attempts
        assert "_retries" not in registry.get(RetryProduct).labels
    finally:
        await broker.shutdown()
        await container.close()


async def test_absent_policy_disables_even_a_broker_retry_default() -> None:
    source = Schedules()
    broker = InMemoryBroker(await_inplace=True).with_middlewares(
        SmartRetryMiddleware(default_retry_label=True, schedule_source=source),
    )
    provider = Resources()
    provider.provide(lambda: Trace(), provides=Trace, scope=Scope.APP)
    provider.provide(DeleteProduct, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    task = Register().register(DeleteProduct, broker)
    await broker.startup()
    try:
        sent = await task.kiq(id=-1)
        assert isinstance((await sent.wait_result()).error, LookupError)
        assert source.pending == []
    finally:
        await broker.shutdown()
        await container.close()


async def test_partial_batch_retry_repeats_original_ids_then_stops() -> None:
    writes: list[list[int]] = []

    class RetryBatch(AbstractBatchUnProjection):
        queue_name: ClassVar[str] = "products"
        retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
            max_attempts=3,
            delay=0,
        )

        async def _es_query(
            self,
            ids: Sequence[int],
        ) -> list[BulkItemResult]:
            writes.append(list(ids))
            return [
                BulkItemResult(
                    id=str(id),
                    status=(500 if id == 8 and len(writes) == 1 else 200),
                )
                for id in ids
            ]

    source = Schedules()
    broker = InMemoryBroker(await_inplace=True).with_middlewares(
        RetryLabelsMiddleware(),
        SmartRetryMiddleware(schedule_source=source),
    )
    provider = Provider()
    provider.provide(RetryBatch, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    task = Register().register(RetryBatch, broker)
    await broker.startup()
    try:
        sent = await task.kiq(ids=[7, 8])
        assert len(source.pending) == 1
        scheduled = source.pending[0]
        assert scheduled.kwargs == {"ids": [7, 8]}
        assert scheduled.task_id == sent.task_id
        await TaskiqScheduler(broker, [source]).on_ready(source, scheduled)
        assert writes == [[7, 8], [7, 8]]
        assert source.pending == []
        assert not (await sent.wait_result()).is_err
    finally:
        await broker.shutdown()
        await container.close()


@pytest.mark.parametrize(
    "values",
    [
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_attempts": 1.5},
        {"delay": -1},
        {"delay": float("inf")},
        {"delay": float("nan")},
        {"delay": "5"},
        {"use_jitter": True},
    ],
)
def test_retry_policy_rejects_invalid_or_unsupported_options(values) -> None:
    with pytest.raises(ValidationError):
        RetryPolicy.model_validate(values)


async def test_schedule_failure_keeps_delivery_and_closes_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RetryProduct(DeleteProduct):
        retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy()

    source = Schedules()
    monkeypatch.setattr(
        source,
        "add_schedule",
        AsyncMock(
            side_effect=ConnectionError("Redis unavailable"),
        ),
    )
    broker = InMemoryBroker(await_inplace=True).with_middlewares(
        RetryLabelsMiddleware(),
        SmartRetryMiddleware(schedule_source=source),
    )
    trace = Trace()
    provider = Resources()
    provider.provide(lambda: trace, provides=Trace, scope=Scope.APP)
    provider.provide(RetryProduct, scope=Scope.REQUEST)
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    task = Register().register(RetryProduct, broker)
    message = TaskiqMessage(
        task_id="retry-store-failure",
        task_name=task.task_name,
        labels=task.labels.copy(),
        args=[],
        kwargs={"id": -1},
    )
    ack = AsyncMock()
    delivery = AckableMessage(
        data=broker.formatter.dumps(message).message,
        ack=ack,
    )
    await broker.startup()
    try:
        with pytest.raises(ConnectionError, match="Redis unavailable"):
            await broker.receiver.callback(delivery)
        ack.assert_not_awaited()
        assert trace.opened == trace.closed == [0]
        assert source.pending == []
    finally:
        await broker.shutdown()
        await container.close()
