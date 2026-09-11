import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitMessage, RabbitQueue
from sqlalchemy import Column, Integer, MetaData, Table, func, select, text

from fastamu.core.config import EventsConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.inbox import writer
from fastamu.infra.db.inbox.table import inbox
from fastamu.infra.db.transaction import (
    TransactionRollbackOnly,
    transaction,
    transactional,
)
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging import inbox as api
from fastamu.tasks.events.factory import BrokerFactory

business = Table(
    "inbox_business", MetaData(), Column("value", Integer, nullable=False)
)


@pytest.fixture
async def runtime(monkeypatch):
    dsn = os.getenv("FASTAMU_TEST_POSTGRESQL")
    if not dsn:
        pytest.skip("Set FASTAMU_TEST_POSTGRESQL")
    db = DBConnection(dsn, 4, 0, 5, 1800)
    schema = "test_inbox_" + uuid4().hex
    async with db.engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    db.engine.update_execution_options(schema_translate_map={None: schema})
    async with db.engine.begin() as conn:
        await conn.run_sync(inbox.create)
        await conn.run_sync(business.create)
        await conn.execute(business.insert().values(value=0))
    monkeypatch.setattr(
        writer,
        "get_settings",
        lambda: SimpleNamespace(tasks=SimpleNamespace(inbox=True)),
    )
    try:
        yield db
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await db.dispose()


async def state(db):
    async with db.session_factory() as session:
        value = await session.scalar(select(business.c.value))
        receipts = await session.scalar(
            select(func.count()).select_from(inbox)
        )
    return value, receipts


async def increment():
    await DBUnitOfWork.current().session.execute(
        business.update().values(value=business.c.value + 1)
    )


@transactional
@api.consumer("stock.apply", message_id=lambda call: call.arguments["id"])
async def apply(id: str):
    await increment()
    return "processed"


async def test_committed_duplicate_skips_body(runtime):
    async with DBUnitOfWork(runtime):
        assert await apply("same") == "processed"
        assert await apply("same") is None
        assert await apply("different") == "processed"
    assert await state(runtime) == (2, 2)


async def test_identity_is_per_consumer(runtime):
    async with DBUnitOfWork(runtime), transaction():
        for name in ("stock.apply", "audit.record"):
            async with api.consume(name, "same") as execute:
                assert execute
                await increment()
    assert await state(runtime) == (2, 2)


@pytest.mark.parametrize("fails", [False, True])
async def test_competing_delivery_waits_for_transaction_outcome(
    runtime, fails
):
    entered = asyncio.Event()
    release = asyncio.Event()
    second = asyncio.Event()

    async def first():
        async with DBUnitOfWork(runtime), transaction():
            async with api.consume("stock.apply", "same") as execute:
                assert execute
                await increment()
                entered.set()
                await asyncio.wait_for(release.wait(), 5)
                if fails:
                    raise ValueError("rollback owner")

    async def competing():
        second.set()
        async with DBUnitOfWork(runtime):
            return await apply("same")

    owner = asyncio.create_task(first())
    await asyncio.wait_for(entered.wait(), 5)
    contender = asyncio.create_task(competing())
    try:
        await asyncio.wait_for(second.wait(), 5)
        await asyncio.sleep(0.02)
        assert not contender.done()
        assert await state(runtime) == (0, 0)
    finally:
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(owner, contender, return_exceptions=True), 5
        )
    assert isinstance(results[0], ValueError) if fails else results[0] is None
    assert results[1] == ("processed" if fails else None)
    assert await state(runtime) == (1, 1)


@pytest.mark.parametrize("failure", ["body", "selector", "commit", "insert"])
async def test_failure_rolls_back_receipt_and_business(
    runtime, monkeypatch, failure
):
    def selector(call):
        if failure == "selector":
            raise ValueError("selector")
        return "same"

    @transactional
    @api.consumer("stock.apply", message_id=selector)
    async def broken():
        await increment()
        if failure == "body":
            raise ValueError("body")

    async with DBUnitOfWork(runtime) as unit:
        with monkeypatch.context() as patch:
            if failure == "commit":
                patch.setattr(
                    unit, "commit", AsyncMock(side_effect=ValueError("commit"))
                )
            elif failure == "insert":
                patch.setattr(
                    api, "claim", AsyncMock(side_effect=ValueError("insert"))
                )
            with pytest.raises(ValueError):
                await broken()
        assert await state(runtime) == (0, 0)
        assert await apply("same") == "processed"
    assert await state(runtime) == (1, 1)


async def test_caught_inner_failure_marks_owner_rollback_only(runtime):
    async with DBUnitOfWork(runtime):
        with pytest.raises(TransactionRollbackOnly):
            async with transaction():
                try:
                    async with api.consume("stock.apply", "same") as execute:
                        assert execute
                        await increment()
                        raise ValueError("caught")
                except ValueError:
                    pass
    assert await state(runtime) == (0, 0)


async def test_cancellation_discards_receipt(runtime):
    entered = asyncio.Event()

    async def receive():
        async with DBUnitOfWork(runtime), transaction():
            async with api.consume("stock.apply", "same") as execute:
                assert execute
                await increment()
                entered.set()
                await asyncio.Event().wait()

    task = asyncio.create_task(receive())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await state(runtime) == (0, 0)
    async with DBUnitOfWork(runtime):
        await apply("same")
    assert await state(runtime) == (1, 1)


@pytest.mark.parametrize("id", [None, "", " ", "a" * 256])
async def test_invalid_identity_rejected_before_business(runtime, id):
    async with DBUnitOfWork(runtime):
        with pytest.raises(ValueError):
            await apply(id)
    assert await state(runtime) == (0, 0)


async def test_wrong_order_and_cross_task_are_rejected(runtime):
    @api.consumer("stock.apply", message_id=lambda call: "same")
    @transactional
    async def wrong_order():
        await increment()

    async with DBUnitOfWork(runtime):
        with pytest.raises(RuntimeError, match="No active"):
            await wrong_order()
        async with transaction():
            with pytest.raises(RuntimeError, match="another"):
                await asyncio.create_task(apply("same"))
    assert await state(runtime) == (0, 0)


async def test_real_router_redelivery_after_commit_has_one_sql_effect(runtime):
    url = os.getenv("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL")
    name = "test.inbox." + uuid4().hex
    broker = BrokerFactory.create(EventsConfig(broker="rabbitmq", url=url))
    done = asyncio.Event()
    outcomes = []
    errors = []

    @broker.subscriber(
        RabbitQueue(name, durable=True), ack_policy=AckPolicy.MANUAL
    )
    async def receive(data: dict, message: RabbitMessage):
        try:
            async with DBUnitOfWork(runtime):
                outcomes.append(await apply(message.message_id))
            assert await state(runtime) == (1, 1)
            if len(outcomes) == 1:
                await message.nack(requeue=True)
            else:
                await message.ack()
                done.set()
        except Exception as error:
            errors.append(error)
            done.set()

    try:
        await broker.start()
        await broker.publish({}, queue=name, message_id="same", persist=True)
        await asyncio.wait_for(done.wait(), 10)
        assert not errors
        assert outcomes == ["processed", None]
        assert await state(runtime) == (1, 1)
    finally:
        queue = await broker.declare_queue(RabbitQueue(name, durable=True))
        await queue.delete(if_unused=False, if_empty=False)
        await broker.stop()
