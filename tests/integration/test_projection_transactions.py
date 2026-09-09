import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from sqlalchemy import text
from taskiq import AckableMessage

from fastamu.common.projections import queue as queue_module
from fastamu.common.projections.base import AbstractProjection
from fastamu.common.projections.queue import ProjectionQueue
from fastamu.core.config import ProjectionConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.tables import ProjectionVersionTable
from fastamu.infra.db.transactions import TransactionRollbackOnly
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.infra.db.versions import ProjectionTicket
from fastamu.tasks.projection import broker as broker_module
from fastamu.tasks.projection import receiver as receiver_module
from fastamu.tasks.projection import registry as registry_module


@pytest.fixture
async def runtime(monkeypatch):
    dsn = os.environ.get("FASTAMU_TEST_POSTGRESQL")
    url = os.environ.get("FASTAMU_RABBIT_TEST_URL")
    if not dsn or not url:
        pytest.skip("Set PostgreSQL and RabbitMQ test URLs")
    name = "test_projection_xid_" + uuid4().hex
    db = DBConnection(dsn, 4, 0, 5, 1800)
    async with db.engine.begin() as connection:
        await connection.run_sync(
            ProjectionVersionTable.__table__.create, checkfirst=True
        )
        await connection.execute(text(f"CREATE TABLE {name} (value int)"))
        await connection.execute(text(f"INSERT INTO {name} VALUES (1)"))
    config = ProjectionConfig(
        url=url,
        max_retries=0,
        retry_delay=0.001,
        failure_queue=name + ".failed",
        expired_queue=name + ".expired",
    )
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    registry = registry_module.ProjectionRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    monkeypatch.setattr(receiver_module, "get_settings", lambda: settings)
    monkeypatch.setattr(queue_module, "get_settings", lambda: settings)
    seen = []

    class Projection(AbstractProjection):
        queue_name = name

        def __init__(self, unit):
            super().__init__(None)
            self.unit = unit

        async def _db_query(self, id):
            return await self.unit.session.scalar(
                text(f"SELECT value FROM {name}")
            )

        async def _es_query(self, document):
            pass

        async def project(self, id):
            seen.append(await self._db_query(id))

    class Dependencies(Provider):
        @provide(scope=Scope.REQUEST)
        async def unit(self) -> AsyncIterator[DBUnitOfWork]:
            async with DBUnitOfWork(db) as unit:
                yield unit

        @provide(scope=Scope.REQUEST, provides=Projection)
        def projection(self, unit: DBUnitOfWork) -> object:
            return Projection(unit)

    broker = broker_module.create_broker(config)
    registry.build(broker)
    await broker.startup()
    container = make_async_container(TaskiqProvider(), Dependencies())
    setup_dishka(container, broker)
    receiver = receiver_module.ProjectionReceiver(broker)
    queue = await broker.write_channel.get_queue(name)
    failed = await broker.write_channel.declare_queue(
        config.failure_queue, durable=True
    )

    inbox = asyncio.Queue()
    consumer_tag = await queue.consume(inbox.put)

    async def receive():
        delivery = await asyncio.wait_for(inbox.get(), 3)
        assert delivery is not None
        await receiver.callback(
            AckableMessage(data=delivery.body, ack=delivery.ack)
        )

    try:
        yield SimpleNamespace(
            db=db,
            name=name,
            seen=seen,
            projection=Projection,
            broker=broker,
            queue=queue,
            failed=failed,
            receiver=receiver,
            receive=receive,
            inbox=inbox,
        )
    finally:
        await queue.cancel(consumer_tag)
        await container.close()
        await queue.delete(if_unused=False, if_empty=False)
        await failed.delete(if_unused=False, if_empty=False)
        await broker.shutdown()
        async with db.engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE {name}"))
            await connection.execute(
                ProjectionVersionTable.__table__.delete().where(
                    ProjectionVersionTable.__table__.c.projection
                    == f"{Projection.__module__}.{Projection.__qualname__}"
                )
            )
        await db.dispose()


@pytest.mark.parametrize("outcome", ["commit", "rollback", "disconnect"])
async def test_publication_before_commit_is_gated_and_recovered(
    runtime, outcome
):
    unit = await DBUnitOfWork(runtime.db).begin()
    try:
        await unit.session.execute(
            text(f"UPDATE {runtime.name} SET value = 2")
        )
        await ProjectionQueue().queue(runtime.projection, 1)
        await runtime.receive()
        assert runtime.seen == []
        if outcome == "commit":
            await unit.commit()
        elif outcome == "rollback":
            await unit.rollback()
        else:
            await unit.session.close()
        assert await runtime.receiver.recovery.replay() == 1
        await runtime.receive()
        assert runtime.seen == ([2] if outcome == "commit" else [])
        failure = await runtime.failed.get(fail=False)
        if outcome == "commit":
            assert failure is None
        else:
            assert failure is not None
            await failure.ack()
        assert runtime.inbox.empty()
    finally:
        await unit.close()


async def test_unroutable_publication_prevents_commit_even_if_caught(runtime):
    async with DBUnitOfWork(runtime.db) as unit:
        await unit.session.execute(
            text(f"UPDATE {runtime.name} SET value = 2")
        )
        await runtime.queue.delete(if_unused=False, if_empty=False)
        with pytest.raises(Exception):
            await ProjectionQueue().queue(runtime.projection, 1)
        with pytest.raises(TransactionRollbackOnly):
            await unit.commit()
        assert (
            await unit.session.scalar(
                text(f"SELECT value FROM {runtime.name}")
            )
            == 1
        )
    runtime.queue = await runtime.broker.write_channel.declare_queue(
        runtime.name,
        durable=True,
        arguments={"x-single-active-consumer": True},
    )


async def test_savepoint_publication_cannot_escape_its_rollback(runtime):
    async with DBUnitOfWork(runtime.db) as unit:
        async with unit.session.begin_nested():
            with pytest.raises(RuntimeError, match="savepoint"):
                await ProjectionQueue().queue(runtime.projection, 1)
        with pytest.raises(TransactionRollbackOnly):
            await unit.commit()
        assert runtime.inbox.empty()


async def test_cancelled_publish_poison_is_not_lost(runtime, monkeypatch):
    async with DBUnitOfWork(runtime.db) as unit:
        monkeypatch.setattr(
            runtime.broker,
            "kick",
            AsyncMock(side_effect=asyncio.CancelledError),
        )
        with pytest.raises(asyncio.CancelledError):
            await ProjectionQueue().queue(runtime.projection, 1)
        with pytest.raises(TransactionRollbackOnly):
            await unit.commit()


async def test_message_keeps_transaction_on_recovery(runtime):
    async with DBUnitOfWork(runtime.db):
        await ProjectionQueue().queue(runtime.projection, 1)
        await runtime.receive()
        assert await runtime.receiver.recovery.replay() == 1
        message = await asyncio.wait_for(runtime.inbox.get(), 3)
        decoded = runtime.broker.formatter.loads(message.body)
        ticket = ProjectionTicket.model_validate_json(
            decoded.labels["projection_version"]
        )
        assert ticket.entries[0].target_id == 1
        assert ticket.entries[0].last_version == 1
        await message.ack()
