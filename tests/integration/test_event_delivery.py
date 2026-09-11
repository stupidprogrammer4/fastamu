"""Real SQL commit boundaries with FastStream's in-process test transports."""

import pytest
from faststream.rabbit import (
    ExchangeType,
    RabbitExchange,
    RabbitQueue,
    TestRabbitBroker,
)
from faststream.redis import TestRedisBroker
from pydantic import BaseModel
from sqlalchemy import Column, Integer, MetaData, Table, insert, select

from fastamu.core.config import EventsConfig
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transaction import transactional
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.events.decorators import event
from fastamu.tasks.events import publisher as event_module
from fastamu.tasks.events.factory import BrokerFactory


class Created(BaseModel):
    id: int


@pytest.mark.parametrize("transport", ["rabbitmq", "redis"])
@pytest.mark.parametrize("abort", [False, True])
async def test_event_is_consumable_only_after_sql_commit(
    tmp_path, monkeypatch, transport, abort
):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/events.db", 3, 0, 5, 1800
    )
    records = Table(
        "records", MetaData(), Column("id", Integer, primary_key=True)
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(records.metadata.create_all)
    config = EventsConfig(
        broker=transport,
        url="amqp://localhost/"
        if transport == "rabbitmq"
        else "redis://localhost/0",
    )
    broker = BrokerFactory.create(config)
    if transport == "rabbitmq":
        exchange = RabbitExchange("events", type=ExchangeType.TOPIC)
        subscriber = broker.subscriber(
            RabbitQueue("created", routing_key="created"), exchange
        )
        test_broker = TestRabbitBroker(broker)
    else:
        subscriber = broker.subscriber("created")
        test_broker = TestRedisBroker(broker)
    monkeypatch.setattr(
        event_module,
        "get_event_transport",
        lambda: (broker, exchange if transport == "rabbitmq" else None),
    )
    seen = []

    @subscriber
    async def consume(data: dict):
        async with db.session_factory() as observer:
            assert await observer.scalar(select(records.c.id)) == data["id"]
        seen.append(data)

    @event("created", payload=lambda call: call.result)
    @transactional
    async def create():
        await DBUnitOfWork.current().session.execute(
            insert(records).values(id=7)
        )
        assert seen == []
        if abort:
            raise ValueError("abort")
        return Created(id=7)

    try:
        async with test_broker:
            async with DBUnitOfWork(db):
                if abort:
                    with pytest.raises(ValueError):
                        await create()
                else:
                    await create()
                    assert seen == [{"id": 7}]
        assert seen == ([] if abort else [{"id": 7}])
    finally:
        await db.dispose()
