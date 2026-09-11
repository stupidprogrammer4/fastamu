"""Independent decorators and SQL boundaries on separate SQLite connections."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from sqlalchemy import Column, Integer, MetaData, Table, insert, select

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transaction import (
    TransactionRollbackOnly,
    current_transaction,
    transaction,
    transactional,
)
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.events.decorators import emit, event
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.projections.decorators import (
    batch_projection,
    fanout_projection,
    projection,
    unprojection,
)


class Changed(BaseModel):
    id: int
    title: str = "original"


class Single(AbstractProjection):
    async def _db_query(self, id):
        return None

    async def _es_query(self, document):
        pass


class Batch(AbstractBatchProjection):
    async def _db_query(self, ids):
        return []

    async def _es_query(self, documents):
        pass


class Fanout(AbstractFanoutProjection):
    async def _db_query(self, id):
        return []

    async def _es_query(self, documents):
        pass


class Delete(AbstractUnProjection):
    async def _es_query(self, id):
        pass


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    db = DBConnection(f"sqlite+aiosqlite:///{tmp_path}/data.db", 4, 0, 5, 1800)
    metadata = MetaData()
    records = Table(
        "records", metadata, Column("id", Integer, primary_key=True)
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    sent = []
    visible = []

    async def send(destination, data):
        async with db.session_factory() as observer:
            visible.append(list(await observer.scalars(select(records.c.id))))
        sent.append((destination, data))

    monkeypatch.setattr("fastamu.tasks.events.publisher.publish", send)
    monkeypatch.setattr("fastamu.tasks.projection.publisher.publish", send)
    try:
        yield SimpleNamespace(
            db=db, records=records, sent=sent, visible=visible
        )
    finally:
        await db.dispose()


async def write(runtime, id=1):
    unit = DBUnitOfWork.current()
    await unit.session.execute(insert(runtime.records).values(id=id))


async def rows(runtime):
    async with runtime.db.session_factory() as observer:
        return list(await observer.scalars(select(runtime.records.c.id)))


async def test_transaction_requires_an_open_unit():
    @transactional
    async def operation():
        pytest.fail("The body must not run without a UoW")

    with pytest.raises(RuntimeError, match="open DBUnitOfWork"):
        await operation()


async def test_session_scope_does_not_implicitly_commit(runtime):
    async with DBUnitOfWork(runtime.db):
        await write(runtime)
    assert await rows(runtime) == []


@pytest.mark.parametrize("operation", ["commit", "rollback"])
async def test_manual_transaction_completion_is_rejected(runtime, operation):
    async with DBUnitOfWork(runtime.db) as unit:
        with pytest.raises(RuntimeError, match="manually"):
            async with transaction():
                await write(runtime)
                await getattr(unit, operation)()


async def test_sequential_transactions_commit_independently(runtime):
    async with DBUnitOfWork(runtime.db):
        for id in (1, 2):
            async with transaction():
                await write(runtime, id)
    assert await rows(runtime) == [1, 2]


async def test_parallel_operations_have_independent_transactions(runtime):
    async def operation(id):
        async with DBUnitOfWork(runtime.db):
            async with transaction():
                await asyncio.sleep(0)
                await write(runtime, id)

    await asyncio.gather(operation(1), operation(2))
    assert sorted(await rows(runtime)) == [1, 2]


async def test_child_task_cannot_use_inherited_transaction(runtime):
    async with DBUnitOfWork(runtime.db):
        async with transaction():

            async def child():
                async with transaction():
                    pytest.fail("Child must not enter inherited transaction")

            with pytest.raises(RuntimeError, match="another or closed task"):
                await asyncio.create_task(child())


@pytest.mark.parametrize("after_commit", [True, False])
async def test_caller_controls_publication_order(runtime, after_commit):
    async def body():
        await write(runtime)
        assert runtime.sent == []
        return Changed(id=1)

    def messages(f):
        return event("created", payload=lambda c: c.result)(
            projection(Single, id=lambda c: c.result.id)(f)
        )

    operation = (
        messages(transactional(body))
        if after_commit
        else transactional(messages(body))
    )
    async with DBUnitOfWork(runtime.db):
        result = await operation()
    assert result == Changed(id=1)
    assert runtime.sent == [(Single, 1), ("created", result.model_dump())]
    assert runtime.visible == ([[1], [1]] if after_commit else [[], []])
    assert await rows(runtime) == [1]


@pytest.mark.parametrize("failure", ["body", "commit", "selector", "delivery"])
async def test_failures_respect_actual_commit_boundary(
    runtime, monkeypatch, failure
):
    def select_payload(call):
        if failure == "selector":
            raise ValueError("selector")
        return call.result

    @event("created", payload=select_payload)
    @transactional
    async def operation():
        await write(runtime)
        if failure == "body":
            raise ValueError("body")
        return Changed(id=1)

    async with DBUnitOfWork(runtime.db) as unit:
        rollback = AsyncMock(wraps=unit.rollback)
        monkeypatch.setattr(unit, "rollback", rollback)
        if failure == "commit":
            monkeypatch.setattr(
                unit, "commit", AsyncMock(side_effect=ValueError("commit"))
            )
        if failure == "delivery":
            monkeypatch.setattr(
                "fastamu.tasks.events.publisher.publish",
                AsyncMock(side_effect=ValueError("delivery")),
            )
        with pytest.raises(ValueError, match=failure):
            await operation()
        assert rollback.await_count == (
            1 if failure in ("body", "commit") else 0
        )
        with pytest.raises(RuntimeError, match="No active"):
            current_transaction()
    assert await rows(runtime) == (
        [1] if failure in ("selector", "delivery") else []
    )
    assert runtime.sent == []


@pytest.mark.parametrize("abort", [True, False])
async def test_nested_messages_are_immediate_even_before_outer_commit(
    runtime, monkeypatch, abort
):
    @event("created", payload=lambda c: c.result)
    @transactional
    async def inner():
        await write(runtime)
        return Changed(id=1)

    @transactional
    async def outer():
        result = await inner()
        assert runtime.visible == [[]]
        result.title = "mutated"
        if abort:
            raise ValueError("outer")

    async with DBUnitOfWork(runtime.db) as unit:
        commit = AsyncMock(wraps=unit.commit)
        monkeypatch.setattr(unit, "commit", commit)
        if abort:
            with pytest.raises(ValueError, match="outer"):
                await outer()
        else:
            await outer()
        assert commit.await_count == (0 if abort else 1)
    assert runtime.sent == [("created", {"id": 1, "title": "original"})]
    assert await rows(runtime) == ([] if abort else [1])


@pytest.mark.parametrize("transactional_inner", [True, False])
async def test_only_nested_sql_failures_mark_rollback_only(
    runtime, transactional_inner
):
    async def fail():
        await write(runtime)
        raise ValueError("inner")

    inner = (
        transactional(fail)
        if transactional_inner
        else event("unused", payload=lambda c: None)(fail)
    )

    @transactional
    async def outer():
        try:
            await inner()
        except ValueError:
            pass

    async with DBUnitOfWork(runtime.db):
        if transactional_inner:
            with pytest.raises(TransactionRollbackOnly):
                await outer()
        else:
            await outer()
    assert await rows(runtime) == ([] if transactional_inner else [1])


@pytest.mark.parametrize("phase", ["body", "commit", "delivery"])
async def test_cancellation_respects_commit_boundary(
    runtime, monkeypatch, phase
):
    reached = asyncio.Event()

    async def pause(*args):
        reached.set()
        await asyncio.Event().wait()

    if phase == "delivery":
        monkeypatch.setattr("fastamu.tasks.events.publisher.publish", pause)

    @event("created", payload=lambda c: Changed(id=1))
    @transactional
    async def write_record():
        await write(runtime)
        if phase == "body":
            await pause()

    async def operation():
        async with DBUnitOfWork(runtime.db) as unit:
            if phase == "commit":
                monkeypatch.setattr(unit, "commit", pause)
            await write_record()

    task = asyncio.create_task(operation())
    await asyncio.wait_for(reached.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rows(runtime) == ([1] if phase == "delivery" else [])


async def test_inner_send_failure_stops_outer_decorator_after_commit(
    runtime, monkeypatch
):
    send = AsyncMock(side_effect=ConnectionError("offline"))
    monkeypatch.setattr("fastamu.tasks.projection.publisher.publish", send)

    @event("created", payload=lambda c: c.result)
    @projection(Single, id=lambda c: 1)
    @transactional
    async def operation():
        await write(runtime)
        return Changed(id=1)

    async with DBUnitOfWork(runtime.db):
        with pytest.raises(ConnectionError, match="offline"):
            await operation()
    send.assert_awaited_once_with(Single, 1)
    assert runtime.sent == []
    assert await rows(runtime) == [1]


async def test_outer_send_failure_does_not_undo_inner_publication(
    runtime, monkeypatch
):
    monkeypatch.setattr(
        "fastamu.tasks.events.publisher.publish",
        AsyncMock(side_effect=ConnectionError("offline")),
    )

    @event("created", payload=lambda c: c.result)
    @projection(Single, id=lambda c: c.result.id)
    @transactional
    async def operation():
        await write(runtime)
        return Changed(id=1)

    async with DBUnitOfWork(runtime.db):
        with pytest.raises(ConnectionError):
            await operation()
    assert runtime.sent == [(Single, 1)]
    assert await rows(runtime) == [1]


async def test_message_decorators_work_without_any_uow(runtime):
    class Service:
        @event(
            "deleted",
            payload=lambda c: Changed(
                id=c.arguments["id"], title=c.arguments["reason"]
            ),
        )
        @unprojection(Delete, id=lambda c: c.arguments["id"])
        async def delete(self, id: int, *, reason: str = "default") -> None:
            pass

    assert DBUnitOfWork.current() is None
    assert await Service().delete(id=7) is None
    assert runtime.sent == [
        (Delete, 7),
        ("deleted", {"id": 7, "title": "default"}),
    ]


@pytest.mark.parametrize(
    "target,decorate,value",
    [
        (Single, projection, 7),
        (Delete, unprojection, 7),
        (Fanout, fanout_projection, 7),
    ],
)
async def test_scalar_decorator_sends_exactly_one_message(
    runtime, target, decorate, value
):
    @decorate(target, id=lambda c: c.result)
    async def operation():
        return value

    assert await operation() == value
    assert runtime.sent == [(target, value)]


async def test_batch_decorator_sends_one_deduplicated_batch(runtime):
    @batch_projection(Batch, ids=lambda c: c.result)
    async def operation():
        return [1, 2, 1]

    assert await operation() == [1, 2, 1]
    assert runtime.sent == [(Batch, [1, 2])]


@pytest.mark.parametrize("value", [[1, 2], [], True, None, "12", 2.0])
@pytest.mark.parametrize(
    "target,decorate",
    [
        (Single, projection),
        (Delete, unprojection),
        (Fanout, fanout_projection),
    ],
)
async def test_scalar_decorators_reject_non_scalar_integer(
    runtime, value, target, decorate
):
    @decorate(target, id=lambda c: value)
    async def operation():
        pass

    with pytest.raises(TypeError, match="integer"):
        await operation()
    assert runtime.sent == []


@pytest.mark.parametrize(
    "value", [1, True, None, "12", [1, "2"], [True], [1, 2.0]]
)
async def test_batch_decorator_validates_whole_batch_before_sending(
    runtime, value
):
    @batch_projection(Batch, ids=lambda c: value)
    async def operation():
        pass

    with pytest.raises(TypeError):
        await operation()
    assert runtime.sent == []


@pytest.mark.parametrize(
    "decorate,base,keyword",
    [
        (projection, Single, "id"),
        (batch_projection, Batch, "ids"),
        (unprojection, Delete, "id"),
        (fanout_projection, Fanout, "id"),
    ],
)
@pytest.mark.parametrize("target", [Single, Batch, Delete, Fanout, object])
def test_decorator_rejects_other_projection_kinds(
    decorate, base, keyword, target
):
    if target is base:
        decorate(target, **{keyword: lambda c: 1})
    else:
        with pytest.raises(TypeError, match="subclass"):
            decorate(target, **{keyword: lambda c: 1})


async def test_explicit_emit_publishes_immediately_without_uow(runtime):
    await emit("created", Changed(id=7))
    assert runtime.sent == [("created", {"id": 7, "title": "original"})]


async def test_skips_preserve_result_identity(runtime):
    result = object()

    @event("unused", payload=lambda c: None)
    @batch_projection(Batch, ids=lambda c: [])
    async def operation():
        return result

    assert await operation() is result
    assert runtime.sent == []


@pytest.mark.parametrize(
    "factory",
    [
        lambda selector: event("created", payload=selector),
        lambda selector: projection(Single, id=selector),
        lambda selector: batch_projection(Batch, ids=selector),
        lambda selector: unprojection(Delete, id=selector),
        lambda selector: fanout_projection(Fanout, id=selector),
    ],
)
def test_selectors_must_be_sync_callables(factory):
    async def selector(call):
        pass

    class AsyncSelector:
        async def __call__(self, call):
            pass

    for invalid in (selector, AsyncSelector(), None):
        with pytest.raises(TypeError):
            factory(invalid)


@pytest.mark.parametrize(
    "decorate",
    [
        transactional,
        event("created", payload=lambda c: None),
        projection(Single, id=lambda c: 1),
        batch_projection(Batch, ids=lambda c: []),
        unprojection(Delete, id=lambda c: 1),
        fanout_projection(Fanout, id=lambda c: 1),
    ],
)
def test_decorators_reject_sync_functions(decorate):
    with pytest.raises(TypeError, match="async function"):
        decorate(lambda: None)


def test_importing_decorators_does_not_construct_brokers_or_load_sql():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from unittest.mock import patch
with patch('fastamu.core.config.get_settings', side_effect=AssertionError):
    from fastamu.messaging.events.decorators import event
    from fastamu.projections.decorators import projection
assert 'fastamu.infra.db.transaction' not in sys.modules
assert 'fastamu.infra.db.uow' not in sys.modules
assert 'fastamu.tasks.events.broker' not in sys.modules
assert 'fastamu.tasks.projection.broker' not in sys.modules
""",
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from fastamu.infra.db.transaction import transactional
assert 'fastamu.messaging.calls' not in sys.modules
assert not any(m.startswith('fastamu.tasks.') for m in sys.modules)
""",
        ],
        check=True,
    )


def test_messaging_contracts_and_outbox_import_without_side_effects():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from unittest.mock import patch
with patch('fastamu.core.config.get_settings', side_effect=AssertionError):
    from fastamu.messaging import Call
    from fastamu.messaging.retry import RetryPolicy
    from fastamu.messaging.outbox.message import OutboxMessage
    from fastamu.projections.definition import ProjectionDefinition
    assert not any(m.startswith('fastamu.infra.db.') for m in sys.modules)
    assert not any(m.startswith('fastamu.tasks.') for m in sys.modules)
    # Import storage first: the package must not pull the writer back through
    # application decorators and create an import-order-dependent cycle.
    from fastamu.infra.db.outbox.writer import append
    from fastamu.messaging.outbox import api
    assert callable(api.record_event)
    assert not any(m.startswith('fastamu.tasks.') for m in sys.modules)
""",
        ],
        check=True,
    )


async def test_event_serializes_transport_payload_before_publication(runtime):
    from datetime import datetime, timezone
    from uuid import UUID

    class Payload(BaseModel):
        id: UUID
        created_at: datetime

    await emit(
        "created",
        Payload(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    assert runtime.sent == [
        (
            "created",
            {
                "id": "12345678-1234-5678-1234-567812345678",
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
    ]


@pytest.mark.parametrize("after_commit", [True, False])
async def test_projection_selector_failure_obeys_caller_composition(
    runtime, after_commit
):
    async def body():
        await write(runtime)

    decorate = projection(Single, id=lambda c: [1, "invalid"])
    operation = (
        decorate(transactional(body))
        if after_commit
        else transactional(decorate(body))
    )
    async with DBUnitOfWork(runtime.db):
        with pytest.raises(TypeError):
            await operation()
    assert await rows(runtime) == ([1] if after_commit else [])
    assert runtime.sent == []
