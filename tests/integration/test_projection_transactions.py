import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from sqlalchemy import text
from taskiq import AckableMessage
from taskiq.exceptions import SendTaskError
from taskiq.receiver import Receiver

from fastamu.core.config import ProjectionConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transaction import transactional
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.projections import definition
from fastamu.projections.base import AbstractProjection
from fastamu.projections.decorators import projection
from fastamu.tasks.projection import broker as broker_module
from fastamu.tasks.projection import publisher as queue_module
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
        await connection.execute(text(f"CREATE TABLE {name} (value int)"))
        await connection.execute(text(f"INSERT INTO {name} VALUES (1)"))
    config = ProjectionConfig(url=url)
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    monkeypatch.setattr(definition, "definitions", {})
    registry = registry_module.ProjectionRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
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
    receiver = Receiver(broker)
    queue = await broker.write_channel.get_queue(name)
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
            receiver=receiver,
            receive=receive,
            inbox=inbox,
        )
    finally:
        await queue.cancel(consumer_tag)
        await container.close()
        await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()
        async with db.engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE {name}"))
        await db.dispose()


def update(runtime, *, abort=False):
    @projection(runtime.projection, id=lambda call: call.result)
    @transactional
    async def operation():
        await DBUnitOfWork.current().session.execute(
            text(f"UPDATE {runtime.name} SET value = 2")
        )
        assert runtime.inbox.empty()
        if abort:
            raise ValueError("abort")
        return 1

    return operation


async def test_queue_receives_work_only_after_commit(runtime):
    async with DBUnitOfWork(runtime.db):
        await update(runtime)()
        await runtime.receive()
        assert runtime.seen == [2]


async def test_rollback_does_not_publish(runtime):
    async with DBUnitOfWork(runtime.db) as unit:
        with pytest.raises(ValueError, match="abort"):
            await update(runtime, abort=True)()
        assert runtime.inbox.empty()
        assert (
            await unit.session.scalar(
                text(f"SELECT value FROM {runtime.name}")
            )
            == 1
        )


async def test_standalone_projection_without_uow(runtime):
    assert DBUnitOfWork.current() is None

    @projection(runtime.projection, id=lambda c: c.result)
    async def operation():
        return 1

    await operation()
    await runtime.receive()
    assert runtime.seen == [1]


async def test_publication_failure_keeps_the_committed_write(runtime):
    await runtime.queue.delete(if_unused=False, if_empty=False)
    try:
        async with DBUnitOfWork(runtime.db):
            with pytest.raises(SendTaskError) as caught:
                await update(runtime)()
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert "did not confirm" in str(caught.value.__cause__)
        async with runtime.db.session_factory() as session:
            assert (
                await session.scalar(text(f"SELECT value FROM {runtime.name}"))
                == 2
            )
    finally:
        runtime.queue = await runtime.broker.write_channel.declare_queue(
            runtime.name,
            durable=True,
            arguments={"x-single-active-consumer": True},
        )
