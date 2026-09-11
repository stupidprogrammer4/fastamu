import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import orjson
import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue
from pydantic import BaseModel
from sqlalchemy import Column, Integer, MetaData, Table, func, select, text
from taskiq import InMemoryBroker
from taskiq.schedule_sources import LabelScheduleSource

from fastamu.core.config import EventsConfig, OutboxConfig, ProjectionConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.outbox import writer
from fastamu.infra.db.outbox.repository import OutboxRepository
from fastamu.infra.db.outbox.table import (
    outbox,
    outbox_batches,
    outbox_control,
)
from fastamu.infra.db.transaction import (
    TransactionRollbackOnly,
    transaction,
    transactional,
)
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.outbox import api, events, projections
from fastamu.messaging.outbox.scope import delivery as delivery_scope
from fastamu.projections import definition
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.tasks.events import publisher as event_publisher
from fastamu.tasks.events.factory import BrokerFactory
from fastamu.tasks.outbox import relay as relay_module
from fastamu.tasks.outbox import scheduler as outbox_scheduler
from fastamu.tasks.outbox.relay import OutboxRelay
from fastamu.tasks.projection import broker as projection_broker
from fastamu.tasks.projection import publisher as projection_publisher
from fastamu.tasks.projection import registry as projection_registry

business = Table(
    "outbox_business_test", MetaData(), Column("id", Integer, primary_key=True)
)


class Event(BaseModel):
    id: int


@pytest.fixture
async def runtime(monkeypatch):
    dsn = os.getenv("FASTAMU_TEST_POSTGRESQL")
    if not dsn:
        pytest.skip("Set FASTAMU_TEST_POSTGRESQL")
    schema = "test_outbox_" + uuid4().hex
    db = DBConnection(dsn, 8, 0, 5, 1800)
    async with db.engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    db.engine.update_execution_options(schema_translate_map={None: schema})
    async with db.engine.begin() as conn:
        await conn.run_sync(lambda sync: outbox.create(sync))
        await conn.run_sync(lambda sync: outbox_batches.create(sync))
        await conn.run_sync(lambda sync: outbox_control.create(sync))
        await conn.run_sync(lambda sync: business.create(sync))
    settings = SimpleNamespace(
        tasks=SimpleNamespace(
            outbox=OutboxConfig(),
            projection=ProjectionConfig(url="amqp://unused"),
            events=EventsConfig(broker="rabbitmq", url="amqp://unused"),
        )
    )
    monkeypatch.setattr(writer, "get_settings", lambda: settings)
    monkeypatch.setattr(events, "get_settings", lambda: settings)
    monkeypatch.setattr(projections, "get_settings", lambda: settings)
    # Decorator module exports share the same settings loader.
    monkeypatch.setattr(
        "fastamu.messaging.outbox.scope.get_settings", lambda: settings
    )
    monkeypatch.setattr(definition, "definitions", {})
    repo = OutboxRepository(db)
    try:
        yield SimpleNamespace(
            db=db, repo=repo, config=settings.tasks.outbox, settings=settings
        )
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await db.dispose()


async def rows(runtime):
    async with runtime.db.session_factory() as session:
        return (await session.execute(select(outbox))).mappings().all()


async def seed(runtime, count=1):
    async with DBUnitOfWork(runtime.db), transaction():
        return [
            await api.record_event("test.created", Event(id=n))
            for n in range(count)
        ]


async def due(runtime):
    async with runtime.db.session_factory.begin() as session:
        await session.execute(
            outbox.update().values(available_at=func.clock_timestamp())
        )


@pytest.mark.parametrize(
    "failure", [None, "business", "selector", "commit", "insert"]
)
async def test_atomic_business_and_message(runtime, failure, monkeypatch):
    def payload(call):
        if failure == "selector":
            raise ValueError("selector")
        return Event(id=call.result)

    @transactional
    @api.event("test.created", payload=payload)
    async def write():
        unit = DBUnitOfWork.current()
        await unit.session.execute(business.insert().values(id=1))
        if failure == "business":
            raise ValueError("business")
        return 1

    async with DBUnitOfWork(runtime.db) as unit:
        if failure == "commit":
            monkeypatch.setattr(
                unit, "commit", AsyncMock(side_effect=ValueError("commit"))
            )
        if failure == "insert":
            monkeypatch.setattr(
                events, "append", AsyncMock(side_effect=ValueError("insert"))
            )
        if failure:
            with pytest.raises(ValueError, match=failure):
                await write()
        else:
            await write()
    async with runtime.db.session_factory() as session:
        assert await session.scalar(
            select(func.count()).select_from(business)
        ) == (not failure)
    assert len(await rows(runtime)) == (not failure)


async def test_swallowed_nested_error_still_rolls_back(runtime):
    @api.event("test.created", payload=lambda call: object())
    async def write():
        await DBUnitOfWork.current().session.execute(
            business.insert().values(id=1)
        )

    async with DBUnitOfWork(runtime.db):
        with pytest.raises(TransactionRollbackOnly):
            async with transaction():
                try:
                    await write()
                except TypeError:
                    pass
    assert await rows(runtime) == []
    async with runtime.db.session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(business))
            == 0
        )


async def test_wrong_decorator_order_rejected_before_business(runtime):
    called = []

    @api.event("test.created", payload=lambda call: Event(id=1))
    @transactional
    async def write():
        called.append(True)

    async with DBUnitOfWork(runtime.db):
        with pytest.raises(RuntimeError, match="No active"):
            await write()
    assert called == []


async def test_immediate_delivery_observes_commit(runtime, monkeypatch):
    published = []

    async def send(message):
        async with runtime.db.session_factory() as observer:
            assert await observer.scalar(select(business.c.id)) == 1
        published.append(message.id)

    original = relay_module.OutboxRelay
    monkeypatch.setattr(
        relay_module,
        "OutboxRelay",
        lambda repo, cfg: original(repo, cfg, send),
    )

    @api.deliver
    @transactional
    @api.event("test.created", payload=lambda call: Event(id=call.result))
    async def write():
        await DBUnitOfWork.current().session.execute(
            business.insert().values(id=1)
        )
        assert published == []
        return 1

    async with DBUnitOfWork(runtime.db):
        assert await write() == 1
    assert len(published) == 1
    assert await rows(runtime) == []


async def test_postcommit_failure_preserves_business_result(
    runtime, monkeypatch
):
    original = relay_module.OutboxRelay
    send = AsyncMock(side_effect=ConnectionError("offline"))
    monkeypatch.setattr(
        relay_module,
        "OutboxRelay",
        lambda repo, cfg: original(repo, cfg, send),
    )

    @api.deliver
    @transactional
    @api.event("test.created", payload=lambda call: Event(id=call.result))
    async def write():
        return 42

    async with DBUnitOfWork(runtime.db):
        assert await write() == 42
    stored = (await rows(runtime))[0]
    assert "offline" in stored["last_error"]
    await due(runtime)
    recovered = AsyncMock()
    assert (
        await original(runtime.repo, runtime.config, recovered).run_once() == 1
    )
    assert recovered.call_args.args[0].id == stored["id"]


async def test_commit_before_sender_dies_is_recoverable(runtime):
    ids = await seed(runtime)
    sent = AsyncMock()
    assert (
        await OutboxRelay(runtime.repo, runtime.config, sent).run_once() == 1
    )
    assert sent.call_args.args[0].id == ids[0]


async def test_fast_path_and_poller_claim_once(runtime):
    ids = await seed(runtime, 12)
    sent = []

    async def send(message):
        await asyncio.sleep(0.01)
        sent.append(message.id)

    relay = OutboxRelay(runtime.repo, runtime.config, send)
    await asyncio.gather(
        relay.run_once(ids), relay.run_once(), relay.run_once()
    )
    assert sorted(sent) == sorted(ids)
    assert await rows(runtime) == []


async def test_crash_after_broker_acceptance_replays_same_id(
    runtime, monkeypatch
):
    ids = await seed(runtime)
    sent = AsyncMock()
    original = runtime.repo.published
    monkeypatch.setattr(
        runtime.repo,
        "published",
        AsyncMock(side_effect=ConnectionError("lost result")),
    )
    relay = OutboxRelay(runtime.repo, runtime.config, sent)
    assert await relay.run_once() == 0
    assert len(await rows(runtime)) == 1
    assert await relay.run_once() == 0
    await due(runtime)
    monkeypatch.setattr(runtime.repo, "published", original)
    assert await relay.run_once() == 1
    assert [call.args[0].id for call in sent.call_args_list] == ids * 2


async def test_partial_publication_only_completes_confirmed_messages(
    runtime, monkeypatch
):
    ids = await seed(runtime, 8)
    failed = {ids[0], ids[4]}

    async def send(message):
        if message.id in failed:
            raise ConnectionError("offline")

    complete = AsyncMock(wraps=runtime.repo.published)
    monkeypatch.setattr(runtime.repo, "published", complete)
    assert (
        await OutboxRelay(runtime.repo, runtime.config, send).run_once(ids)
        == 6
    )
    assert complete.await_count == 2
    assert all(len(call.args[0]) == 3 for call in complete.await_args_list)
    remaining = await rows(runtime)
    assert {row["id"] for row in remaining} == failed
    for row in remaining:
        assert bool(row["last_error"]) == (row["id"] in failed)
        assert row["attempts"] == 1


async def test_bulk_confirmation_preserves_newer_claims(runtime):
    ids = await seed(runtime, 4)
    original = await runtime.repo.claim(ids=ids, limit=4, lease_seconds=30)
    async with runtime.db.session_factory.begin() as session:
        await session.execute(
            outbox.update()
            .where(outbox.c.id == ids[0])
            .values(available_at=func.clock_timestamp())
        )
    replacement = await runtime.repo.claim(
        ids=[ids[0]], limit=1, lease_seconds=30
    )
    assert await runtime.repo.published(original) == 3
    assert await runtime.repo.published(original) == 0
    stored = {row["id"]: row for row in await rows(runtime)}
    assert set(stored) == {ids[0]}
    assert stored[ids[0]]["claim_token"] == replacement[0].token
    assert await runtime.repo.published(replacement) == 1


async def test_dead_owner_cannot_complete_new_claim(runtime):
    await seed(runtime)
    first = (await runtime.repo.claim(limit=1, lease_seconds=30))[0]
    assert await runtime.repo.claim(limit=1, lease_seconds=30) == []
    await due(runtime)
    second = (await runtime.repo.claim(limit=1, lease_seconds=30))[0]
    assert first.token != second.token
    assert not await runtime.repo.published([first])
    assert not await runtime.repo.reschedule(first, ValueError(), 20)
    assert await runtime.repo.published([second]) == 1


async def test_cancelled_sender_leaves_recoverable_lease(runtime):
    await seed(runtime)
    entered = asyncio.Event()

    async def send(message):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        OutboxRelay(runtime.repo, runtime.config, send).run_once()
    )
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(await rows(runtime)) == 1
    await due(runtime)
    assert (
        await OutboxRelay(runtime.repo, runtime.config, AsyncMock()).run_once()
        == 1
    )


async def test_disabled_polling_does_not_disable_explicit_recovery(runtime):
    await seed(runtime)
    config = runtime.config.model_copy(update={"polling": False})
    send = AsyncMock()
    relay = OutboxRelay(runtime.repo, config, send)
    send.assert_not_called()
    assert await relay.run_once() == 1


async def test_all_projection_contracts(runtime):
    class Single(AbstractProjection):
        queue_name = "test.outbox"
        outbox_name = "test.single"

        async def _db_query(self, id):
            pass

        async def _es_query(self, document):
            pass

    class Batch(AbstractBatchProjection):
        queue_name = "test.outbox"
        outbox_name = "test.batch"

        async def _db_query(self, ids):
            pass

        async def _es_query(self, documents):
            pass

    class Fanout(AbstractFanoutProjection):
        queue_name = "test.outbox"
        outbox_name = "test.fanout"

        async def _db_query(self, id):
            pass

        async def _es_query(self, documents):
            pass

    class Remove(AbstractUnProjection):
        queue_name = "test.outbox"
        outbox_name = "test.remove"

        async def _es_query(self, id):
            pass

    @transactional
    @api.projection(Single, id=lambda call: call.result)
    @api.batch_projection(Batch, ids=lambda call: [call.result, call.result])
    @api.fanout_projection(Fanout, id=lambda call: call.result)
    @api.unprojection(Remove, id=lambda call: call.result)
    async def write():
        return 5

    async with DBUnitOfWork(runtime.db):
        await write()
        async with transaction():
            assert await api.record_batch_projection(Batch, ids=[]) is None
    stored = await rows(runtime)
    assert {r["target"]: orjson.loads(r["payload"]) for r in stored} == {
        "test.single": {"argument": 5},
        "test.batch": {"argument": [5]},
        "test.fanout": {"argument": 5},
        "test.remove": {"argument": 5},
    }
    assert all(isinstance(r["id"], UUID) for r in stored)


async def test_inherited_delivery_scope_cannot_cross_tasks(runtime):
    async with DBUnitOfWork(runtime.db), delivery_scope():
        async with transaction():
            with pytest.raises(RuntimeError):
                await asyncio.create_task(
                    api.record_event("test.created", Event(id=1))
                )
    assert await rows(runtime) == []


async def test_claim_does_not_hold_connection_during_publish(runtime):
    await seed(runtime)

    async def send(message):
        assert runtime.db.engine.pool.checkedout() == 0

    assert (
        await OutboxRelay(runtime.repo, runtime.config, send).run_once() == 1
    )


@pytest.mark.parametrize("unavailable", ["claimed", "delayed"])
async def test_immediate_delivery_bounds_ids_and_skips_unavailable_prefix(
    runtime, monkeypatch, unavailable
):
    ids = await seed(runtime, 17)
    prefix = ids[: runtime.config.concurrency]
    if unavailable == "claimed":
        await runtime.repo.claim(
            ids=prefix, limit=len(prefix), lease_seconds=30
        )
    elif unavailable == "delayed":
        async with runtime.db.session_factory.begin() as session:
            await session.execute(
                outbox.update()
                .where(outbox.c.id.in_(prefix))
                .values(
                    available_at=func.statement_timestamp()
                    + text("interval '1 day'")
                )
            )
    claim = AsyncMock(wraps=runtime.repo.claim)
    monkeypatch.setattr(runtime.repo, "claim", claim)
    send = AsyncMock()
    assert await OutboxRelay(runtime.repo, runtime.config, send).run_once(
        ids
    ) == len(ids) - len(prefix)
    assert {call.args[0].id for call in send.await_args_list} == set(
        ids[len(prefix) :]
    )
    requested = [call.kwargs["ids"] for call in claim.await_args_list]
    assert all(len(group) <= runtime.config.concurrency for group in requested)
    assert [id for group in requested for id in group] == ids
    assert all(
        row["attempts"] == int(unavailable == "claimed")
        for row in await rows(runtime)
        if row["id"] in prefix
    )


async def test_scheduler_leaves_future_messages_unassigned(runtime):
    ids = await seed(runtime, 6)
    future = ids[2:]
    async with runtime.db.session_factory.begin() as session:
        await session.execute(
            outbox.update()
            .where(outbox.c.id.in_(future))
            .values(
                available_at=func.statement_timestamp()
                + text("interval '1 day'")
            )
        )
    batches = await runtime.repo.plan_batches(
        batch_size=1000, max_batches=10, lease_seconds=60
    )
    assert len(batches) == 1 and batches[0].size == 2
    send = AsyncMock()
    assert (
        await OutboxRelay(runtime.repo, runtime.config, send).run_batch(
            batches[0].id
        )
        == 2
    )
    assert {call.args[0].id for call in send.await_args_list} == set(ids[:2])
    assert all(
        row["batch_id"] is None and row["attempts"] == 0
        for row in await rows(runtime)
        if row["id"] in future
    )


@pytest.mark.parametrize(
    "count,sizes",
    [
        (0, []),
        (300, [300]),
        (1000, [1000]),
        (1001, [1000, 1]),
        (5000, [1000] * 5),
        (10001, [1000] * 10),
    ],
)
async def test_scheduler_splits_bounded_work(runtime, count, sizes):
    if count:
        async with runtime.db.session_factory.begin() as session:
            await session.execute(
                outbox.insert(),
                [
                    {
                        "id": uuid4(),
                        "kind": "event",
                        "target": "test.created",
                        "payload": b"{}",
                    }
                    for _ in range(count)
                ],
            )
    batches = await runtime.repo.plan_batches(
        batch_size=1000, max_batches=10, lease_seconds=60
    )
    assert [batch.size for batch in batches] == sizes
    assert (
        await runtime.repo.plan_batches(
            batch_size=1000, max_batches=10, lease_seconds=60
        )
        == []
    )


async def test_schedulers_cannot_exceed_global_batch_cap(runtime):
    await seed(runtime, 15)
    planned = await asyncio.gather(
        *[
            runtime.repo.plan_batches(
                batch_size=2, max_batches=5, lease_seconds=60
            )
            for _ in range(3)
        ]
    )
    assert len([batch for group in planned for batch in group]) == 5
    async with runtime.db.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(outbox_batches)
            )
            == 5
        )


async def test_parallel_batch_workers_and_immediate_sender_do_not_overlap(
    runtime,
):
    ids = await seed(runtime, 25)
    batches = await runtime.repo.plan_batches(
        batch_size=5, max_batches=5, lease_seconds=60
    )
    sent = []

    async def send(message):
        sent.append(message.id)
        await asyncio.sleep(0.005)

    relay = OutboxRelay(runtime.repo, runtime.config, send)
    await asyncio.gather(
        relay.run_once(ids),
        *[relay.run_batch(batch.id) for batch in batches],
        relay.run_batch(batches[0].id),
    )
    assert sorted(sent) == sorted(ids)
    assert await rows(runtime) == []


async def test_lost_scheduled_job_can_be_reassigned(runtime):
    ids = await seed(runtime, 4)
    batches = await runtime.repo.plan_batches(
        batch_size=4, max_batches=1, lease_seconds=60
    )
    assert (
        await runtime.repo.plan_batches(
            batch_size=4, max_batches=1, lease_seconds=60
        )
        == []
    )
    async with runtime.db.session_factory.begin() as session:
        await session.execute(
            outbox_batches.update().values(expires_at=func.clock_timestamp())
        )
    replacement = await runtime.repo.plan_batches(
        batch_size=4, max_batches=1, lease_seconds=60
    )
    assert replacement[0].id != batches[0].id
    send = AsyncMock()
    relay = OutboxRelay(runtime.repo, runtime.config, send)
    assert await relay.run_batch(batches[0].id) == 0
    assert await relay.run_batch(replacement[0].id) == len(ids)


async def test_batch_failure_waits_for_next_schedule(runtime):
    await seed(runtime, 4)
    batch = (
        await runtime.repo.plan_batches(
            batch_size=4, max_batches=1, lease_seconds=60
        )
    )[0]
    send = AsyncMock(side_effect=ConnectionError("offline"))
    assert (
        await OutboxRelay(runtime.repo, runtime.config, send).run_batch(
            batch.id
        )
        == 0
    )
    assert send.await_count == 4
    assert all(row["batch_id"] is None for row in await rows(runtime))
    assert (
        await runtime.repo.plan_batches(
            batch_size=4, max_batches=1, lease_seconds=60
        )
        == []
    )


@pytest.mark.parametrize("enabled", [False, True])
async def test_native_interval_scheduler_registration(
    runtime, monkeypatch, enabled
):
    runtime.settings.tasks.outbox.polling = enabled
    monkeypatch.setattr(
        outbox_scheduler, "get_settings", lambda: runtime.settings
    )
    broker = InMemoryBroker()
    outbox_scheduler.register(broker)
    outbox_scheduler.register(broker)
    source = LabelScheduleSource(broker)
    await source.startup()
    schedules = await source.get_schedules()
    assert len(schedules) == int(enabled)
    if enabled:
        assert schedules[0].task_name == "fastamu.outbox.recover"
        assert schedules[0].interval.total_seconds() == 20
        assert broker.find_task("fastamu.outbox.publish_batch") is not None


async def test_native_scheduler_dispatches_and_executes_parallel_jobs(
    runtime, monkeypatch
):
    ids = await seed(runtime, 11)
    runtime.config.batch_size = 3
    runtime.config.max_parallel_batches = 5
    monkeypatch.setattr(
        outbox_scheduler, "get_settings", lambda: runtime.settings
    )

    class DatabaseProvider(Provider):
        @provide(scope=Scope.APP)
        def connection(self) -> DBConnection:
            return runtime.db

    broker = InMemoryBroker()
    container = make_async_container(TaskiqProvider(), DatabaseProvider())
    setup_dishka(container, broker)
    monkeypatch.setattr(
        outbox_scheduler,
        "import_module",
        lambda name: SimpleNamespace(broker=broker),
    )
    sent = []
    complete = asyncio.Event()

    async def publish(message):
        sent.append(message.id)
        if len(sent) == len(ids):
            complete.set()

    monkeypatch.setattr(
        outbox_scheduler,
        "OutboxRelay",
        lambda repo, config: OutboxRelay(repo, config, publish),
    )
    outbox_scheduler.register(broker)
    await broker.startup()
    try:
        task = broker.find_task("fastamu.outbox.recover")
        assert task is not None
        job = await task.kiq()
        result = await job.wait_result(timeout=10)
        assert not result.is_err
        assert result.return_value == 4
        await asyncio.wait_for(complete.wait(), timeout=10)
        async with asyncio.timeout(10):
            while await rows(runtime):
                await asyncio.sleep(0.01)
        assert sorted(sent) == sorted(ids)
    finally:
        await broker.wait_all()
        await broker.shutdown()
        await container.close()


@pytest.mark.parametrize("routable", [True, False])
async def test_real_rabbit_event_confirm_and_identity(
    runtime, monkeypatch, routable
):
    url = os.getenv("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL")
    name = "test.outbox." + uuid4().hex
    broker = BrokerFactory.create(EventsConfig(broker="rabbitmq", url=url))
    exchange = RabbitExchange(name, type=ExchangeType.TOPIC, durable=True)
    await broker.connect()
    declared = await broker.declare_exchange(exchange)
    queue = await broker.declare_queue(RabbitQueue(name, durable=True))
    try:
        if routable:
            await queue.bind(declared, routing_key="test.created")
        monkeypatch.setattr(
            event_publisher, "get_event_transport", lambda: (broker, exchange)
        )
        ids = await seed(runtime)
        relay = OutboxRelay(runtime.repo, runtime.config)
        assert await relay.run_once() == int(routable)
        stored = await rows(runtime)
        if routable:
            message = await queue.get(timeout=5)
            assert message.message_id == str(ids[0])
            assert orjson.loads(message.body) == {"id": 0}
            await message.ack()
            assert stored == []
        else:
            assert len(stored) == 1
            assert stored[0]["last_error"]
    finally:
        await queue.delete(if_unused=False, if_empty=False)
        await declared.delete(if_unused=False)
        await broker.stop()


async def test_real_projection_task_reuses_outbox_id(runtime, monkeypatch):
    url = os.getenv("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL")

    class Project(AbstractProjection):
        queue_name = "test.outbox." + uuid4().hex
        outbox_name = "test.project"

        async def _db_query(self, id):
            pass

        async def _es_query(self, document):
            pass

    registry = projection_registry.ProjectionRegistry()
    broker = projection_broker.create_broker(ProjectionConfig(url=url))
    registry.build(broker)
    monkeypatch.setattr(projection_publisher, "registry", registry)
    monkeypatch.setattr(
        projection_publisher, "get_settings", lambda: runtime.settings
    )
    await broker.startup()
    queue = await broker.write_channel.get_queue(Project.queue_name)
    inbox = asyncio.Queue()
    consumer = await queue.consume(inbox.put)
    try:
        async with DBUnitOfWork(runtime.db), transaction():
            id = await api.record_projection(Project, id=42)
        relay = OutboxRelay(runtime.repo, runtime.config)
        complete = runtime.repo.published
        monkeypatch.setattr(
            runtime.repo,
            "published",
            AsyncMock(side_effect=ConnectionError("commit lost")),
        )
        assert await relay.run_once() == 0
        await due(runtime)
        monkeypatch.setattr(runtime.repo, "published", complete)
        assert await relay.run_once() == 1
        for _ in range(2):
            message = await asyncio.wait_for(inbox.get(), 5)
            decoded = broker.formatter.loads(message.body)
            assert decoded.task_id == str(id)
            assert decoded.args == [42]
            assert message.message_id == str(id)
            await message.ack()
    finally:
        await queue.cancel(consumer)
        await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()
