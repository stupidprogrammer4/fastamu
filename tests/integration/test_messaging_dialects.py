import asyncio
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select

from fastamu.core.config import EventsConfig, OutboxConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.inbox import writer as inbox_writer
from fastamu.infra.db.inbox.table import inbox
from fastamu.infra.db.outbox import writer as outbox_writer
from fastamu.infra.db.outbox.repository import OutboxRepository
from fastamu.infra.db.outbox.table import (
    outbox,
    outbox_batches,
    outbox_control,
)
from fastamu.infra.db.transaction import transaction
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging import inbox as inbox_api
from fastamu.messaging.outbox import api as outbox_api
from fastamu.messaging.outbox import events
from fastamu.tasks.outbox.relay import OutboxRelay
from tests.integration.test_outbox import Event

business = Table(
    "portable_business", MetaData(), Column("value", Integer, nullable=False)
)


@pytest.fixture(params=["postgresql", "mysql", "sqlite"])
async def runtime(request, tmp_path, monkeypatch):
    backend = request.param
    dsn = (
        f"sqlite+aiosqlite:///{tmp_path}/messages.db"
        if backend == "sqlite"
        else os.getenv(f"FASTAMU_TEST_{backend.upper()}")
    )
    if not dsn:
        pytest.skip(f"Set FASTAMU_TEST_{backend.upper()}")
    db = DBConnection(dsn, 8, 0, 5, 1800)
    tables = [outbox, outbox_batches, outbox_control, inbox, business]
    async with db.engine.begin() as connection:
        for table in tables:
            await connection.run_sync(table.create)
        await connection.execute(business.insert().values(value=0))
    config = OutboxConfig(batch_size=5, max_parallel_batches=3)
    settings = SimpleNamespace(
        tasks=SimpleNamespace(
            inbox=True,
            outbox=config,
            events=EventsConfig(broker="rabbitmq", url="amqp://unused"),
        )
    )
    for module in (inbox_writer, outbox_writer, events):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    try:
        yield SimpleNamespace(db=db, repo=OutboxRepository(db), config=config)
    finally:
        async with db.engine.begin() as connection:
            for table in reversed(tables):
                await connection.run_sync(table.drop)
        await db.dispose()


async def seed(runtime, count):
    async with DBUnitOfWork(runtime.db), transaction():
        return [
            await outbox_api.record_event("test.created", Event(id=n))
            for n in range(count)
        ]


async def consume(runtime, id):
    async with DBUnitOfWork(runtime.db) as unit, transaction():
        async with inbox_api.consume("apply", id) as execute:
            if execute:
                await unit.session.execute(
                    business.update().values(value=business.c.value + 1)
                )
            return execute


async def test_portable_plan_publish_delete_and_consume(runtime):
    await seed(runtime, 17)

    async def plan():
        return await runtime.repo.plan_batches(
            batch_size=5, max_batches=3, lease_seconds=60
        )

    groups = await asyncio.gather(plan(), plan(), plan())
    batches = [batch for group in groups for batch in group]
    assert len(batches) == 3
    sent = []

    async def publish(message):
        sent.append(message.id)
        assert await consume(runtime, str(message.id))

    relay = OutboxRelay(runtime.repo, runtime.config, publish)
    assert (
        sum(
            await asyncio.gather(
                *(relay.run_batch(batch.id) for batch in batches)
            )
        )
        == 15
    )
    remaining = await plan()
    assert len(remaining) == 1 and remaining[0].size == 2
    assert await relay.run_batch(remaining[0].id) == 2
    assert len(sent) == len(set(sent)) == 17
    async with runtime.db.session_factory() as session:
        assert (await session.execute(select(outbox))).first() is None
        assert await session.scalar(select(business.c.value)) == 17


async def test_portable_inbox_rollback_duplicate_and_concurrency(runtime):
    with pytest.raises(ValueError):
        async with DBUnitOfWork(runtime.db) as unit, transaction():
            async with inbox_api.consume("apply", "same") as execute:
                assert execute
                await unit.session.execute(business.update().values(value=1))
                raise ValueError("rollback")
    async with runtime.db.session_factory() as session:
        assert (await session.execute(select(inbox))).first() is None
        assert await session.scalar(select(business.c.value)) == 0
    results = await asyncio.gather(
        *(consume(runtime, "same") for _ in range(5))
    )
    assert sum(results) == 1
    assert not await consume(runtime, "same")
    assert await consume(runtime, "different")
    async with runtime.db.session_factory() as session:
        assert await session.scalar(select(business.c.value)) == 2


async def test_portable_claims_are_exclusive(runtime):
    ids = await seed(runtime, 12)
    claims = await asyncio.gather(
        *[
            runtime.repo.claim(ids=ids, limit=4, lease_seconds=30)
            for _ in range(3)
        ]
    )
    owned = [item for group in claims for item in group]
    assert len(owned) == len({item.message.id for item in owned}) == 12
    assert await runtime.repo.published(owned) == 12
    assert await runtime.repo.published(owned) == 0
