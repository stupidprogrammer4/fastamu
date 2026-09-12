import asyncio
import logging
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from taskiq import InMemoryBroker
from taskiq.exceptions import SendTaskError

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transaction import transaction, transactional
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.tasks.projection.delivery import decorators
from fastamu.tasks.projection.delivery.fallback import PublicationFallback
from fastamu.tasks.projection.delivery.register import Register
from tests.unit.test_projection import (
    ProductBatchUnProjection,
    ProductUnProjection,
)
from tests.unit.test_projection_failure_queue import make_queue


@pytest.fixture
def publisher(monkeypatch):
    registry = Register()
    broker = InMemoryBroker()
    broker.kick = AsyncMock()
    for projection in (
        ProductUnProjection,
        ProductBatchUnProjection,
    ):
        monkeypatch.setattr(
            projection, "queue_name", "products", raising=False
        )
        registry.register(projection, broker)
    monkeypatch.setattr(decorators, "register", registry)
    return broker


async def test_decorator_publishes_once_after_success_and_preserves_result(
    publisher,
):
    result = {"id": 42}

    @decorators.unproject(ProductUnProjection, lambda value: value["id"])
    async def command(*, label: str) -> dict[str, int]:
        publisher.kick.assert_not_awaited()
        assert label == "update"
        return result

    assert await command(label="update") is result
    assert command.__name__ == "command"
    publisher.kick.assert_awaited_once()
    message = publisher.formatter.loads(
        publisher.kick.call_args.args[0].message
    )
    assert message.kwargs == {"id": 42}
    assert message.labels["queue_name"] == "products"


async def test_batch_is_one_message_not_a_loop(publisher):
    ids = tuple(range(1000))

    @decorators.batch_unproject(
        ProductBatchUnProjection, lambda result: result
    )
    async def command() -> tuple[int, ...]:
        return ids

    assert await command() is ids
    publisher.kick.assert_awaited_once()
    message = publisher.formatter.loads(
        publisher.kick.call_args.args[0].message
    )
    assert message.kwargs == {"ids": list(ids)}


@pytest.mark.parametrize(
    "error", [ValueError("command failed"), asyncio.CancelledError()]
)
async def test_body_failure_or_cancellation_does_not_publish(publisher, error):
    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        raise error

    with pytest.raises(type(error)):
        await command()
    publisher.kick.assert_not_awaited()


@pytest.mark.parametrize("invalid_id", [True, "42", None])
async def test_invalid_mapper_output_is_not_published(publisher, invalid_id):
    @decorators.project(ProductUnProjection, lambda result: invalid_id)
    async def command() -> int:
        return 42

    with pytest.raises(ValidationError):
        await command()
    publisher.kick.assert_not_awaited()


async def test_mapper_exception_propagates_without_publishing(publisher):
    def mapper(result: int) -> int:
        raise LookupError("mapping failed")

    @decorators.project(ProductUnProjection, mapper)
    async def command() -> int:
        return 42

    with pytest.raises(LookupError, match="mapping failed"):
        await command()
    publisher.kick.assert_not_awaited()


async def test_publish_failure_does_not_rerun_command(publisher):
    calls = []
    publisher.kick.side_effect = ConnectionError("offline")

    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        calls.append(42)
        return 42

    with pytest.raises(SendTaskError) as caught:
        await command()
    assert isinstance(caught.value.__cause__, ConnectionError)
    assert calls == [42]
    publisher.kick.assert_awaited_once()


@pytest.fixture
def repaired(monkeypatch, publisher):
    """Wire a failure queue for the registered projections, as startup does."""
    queue, _ = make_queue()
    names = [
        decorators.register.get(projection).task_name
        for projection in (ProductUnProjection, ProductBatchUnProjection)
    ]
    fallback = PublicationFallback()
    fallback.use(queue, names)
    monkeypatch.setattr(decorators, "fallback", fallback)
    return queue, names


async def test_an_unpublished_id_is_queued_rather_than_raised(
    publisher,
    repaired,
):
    queue, (single, _) = repaired
    publisher.kick.side_effect = ConnectionError("offline")

    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        return 42

    assert await command() == 42
    records = await queue.take(single, 10)
    assert [record.input_id for record in records] == [42]
    # The cause survives: a transport error's own message says nothing.
    assert records[0].error == "Cannot send task to the queue: offline"


async def test_an_unpublished_batch_is_queued_whole(publisher, repaired):
    queue, (_, batch) = repaired
    publisher.kick.side_effect = ConnectionError("offline")

    @decorators.batch_unproject(ProductBatchUnProjection, lambda r: r)
    async def command() -> list[int]:
        return [7, 8]

    assert await command() == [7, 8]
    records = await queue.take(batch, 10)
    assert [record.input_id for record in records] == [7, 8]


async def test_a_projection_without_a_repair_target_still_raises(
    publisher,
    monkeypatch,
):
    queue, _ = make_queue()
    fallback = PublicationFallback()
    fallback.use(queue, [])
    monkeypatch.setattr(decorators, "fallback", fallback)
    publisher.kick.side_effect = ConnectionError("offline")

    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        return 42

    with pytest.raises(SendTaskError):
        await command()


async def test_an_unreachable_queue_does_not_fail_a_committed_write(
    publisher,
    repaired,
    caplog,
):
    """Queueing is the backstop, not a second system the write depends on."""
    queue, _ = repaired
    publisher.kick.side_effect = ConnectionError("offline")
    queue.record = AsyncMock(side_effect=ConnectionError("Redis down"))

    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        return 42

    with caplog.at_level(logging.ERROR):
        assert await command() == 42
    assert "Could not queue 1" in caplog.text
    assert "Redis down" in caplog.text
    assert "offline" in caplog.text


@pytest.fixture
async def database(tmp_path) -> AsyncIterator[DBConnection]:
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/command.db", 2, 0, 5, 1800
    )
    async with db.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE records (id INTEGER)"))
    try:
        yield db
    finally:
        await db.dispose()


async def test_transaction_composition_commits_before_publish(
    publisher, database
):
    async def check_committed(message):
        async with database.engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT id FROM records"))
            ).scalar() == 42

    publisher.kick.side_effect = check_committed

    @decorators.project(ProductUnProjection, lambda result: result)
    @transactional
    async def command() -> int:
        await DBUnitOfWork.current().session.execute(
            text("INSERT INTO records VALUES (42)")
        )
        return 42

    async with database.uow():
        assert await command() == 42
    publisher.kick.assert_awaited_once()


async def test_project_does_not_reject_or_inspect_an_active_transaction(
    publisher, database
):
    @decorators.project(ProductUnProjection, lambda result: result)
    async def command() -> int:
        return 42

    async with database.uow():
        async with transaction():
            assert await command() == 42
            publisher.kick.assert_awaited_once()


async def test_commit_failure_prevents_publication(
    publisher, database, monkeypatch
):
    @decorators.project(ProductUnProjection, lambda result: result)
    @transactional
    async def command() -> int:
        await DBUnitOfWork.current().session.execute(
            text("INSERT INTO records VALUES (42)")
        )
        return 42

    async with database.uow() as unit:
        monkeypatch.setattr(
            unit,
            "commit",
            AsyncMock(side_effect=RuntimeError("commit failed")),
        )
        with pytest.raises(RuntimeError, match="commit failed"):
            await command()
    publisher.kick.assert_not_awaited()
    async with database.engine.connect() as connection:
        assert (
            await connection.execute(text("SELECT count(*) FROM records"))
        ).scalar() == 0
