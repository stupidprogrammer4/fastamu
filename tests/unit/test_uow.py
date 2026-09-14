from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import bindparam, insert, select, update
from sqlmodel import Field

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.table import BaseTable
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork


class UowRecord(IdentifiedEntity, BaseTable, table=True):
    name: str = Field(default="pending")


@pytest.mark.parametrize("streamed", [False, True])
async def test_execution_preserves_rows_and_transaction_ownership(
    tmp_path, streamed
):
    database = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/execution.db",
        2,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    table = UowRecord.__table__
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(table.create)
        async with database.uow() as unit:
            stmt = insert(table)
            await unit.execute(stmt, {"id": 1, "name": "first"})
            await unit.execute(
                stmt,
                [{"id": 2, "name": "second"}, {"id": 3, "name": "third"}],
            )
            stmt = (
                select(table.c.id, table.c.name)
                .where(table.c.id >= bindparam("minimum"))
                .order_by(table.c.id)
            )
            if streamed:
                result = await unit.stream(
                    stmt,
                    {"minimum": 2},
                    execution_options={"yield_per": 1},
                    bind_arguments={"mapper": UowRecord},
                )
                try:
                    rows = [dict(row) async for row in result.mappings()]
                finally:
                    await result.close()
                assert result.closed
            else:
                result = await unit.execute(
                    stmt,
                    {"minimum": 2},
                    execution_options={"autoflush": False},
                    bind_arguments={"mapper": UowRecord},
                )
                rows = [dict(row) for row in result.mappings()]
            assert rows == [
                {"id": 2, "name": "second"},
                {"id": 3, "name": "third"},
            ]
            assert unit.in_transaction
            async with database.uow() as observer:
                stmt = select(table.c.id)
                assert (await observer.execute(stmt)).all() == []
        # Scope exit rolls back: execution and consumption never commit.
        async with database.uow() as observer:
            stmt = select(table.c.id)
            assert (await observer.execute(stmt)).all() == []
    finally:
        await database.dispose()


@pytest.mark.parametrize("streamed", [False, True])
async def test_execution_options_override_statement_options_without_mutation(
    tmp_path, streamed
):
    database = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/options.db",
        2,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(UowRecord.__table__.create)
        async with database.uow() as unit:
            row = UowRecord(name="stored")
            unit.session.add(row)
            await unit.flush()
            row.name = "pending"
            stmt = select(UowRecord).execution_options(populate_existing=True)
            options = {"populate_existing": False}
            if streamed:
                result = await unit.stream(stmt, execution_options=options)
                try:
                    found = await result.scalar_one()
                finally:
                    await result.close()
            else:
                result = await unit.execute(stmt, execution_options=options)
                found = result.scalar_one()
            assert found is row
            assert row.name == "pending"
            assert row in unit.session.dirty
            assert options == {"populate_existing": False}
            assert stmt.get_execution_options()["populate_existing"] is True

            # Without the override, the statement's refresh takes effect.
            if streamed:
                result = await unit.stream(stmt)
                try:
                    found = await result.scalar_one()
                finally:
                    await result.close()
            else:
                found = (await unit.execute(stmt)).scalar_one()
            assert found is row
            assert row.name == "stored"
            assert row not in unit.session.dirty
    finally:
        await database.dispose()


async def test_scope_only_opens_and_closes_session():
    session = SimpleNamespace(
        commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock()
    )
    unit = UnitOfWork(SimpleNamespace(session_factory=lambda: session))
    async with unit:
        assert unit.session is session
        assert UnitOfWork.current() is unit
    session.commit.assert_not_awaited()
    session.close.assert_awaited_once()
    assert UnitOfWork.current() is None
    with pytest.raises(RuntimeError, match="not open"):
        _ = unit.session


async def test_close_failure_still_clears_context():
    session = SimpleNamespace(
        close=AsyncMock(side_effect=RuntimeError("close"))
    )
    unit = UnitOfWork(SimpleNamespace(session_factory=lambda: session))
    with pytest.raises(RuntimeError, match="close"):
        async with unit:
            pass
    assert unit._session is None
    assert UnitOfWork.current() is None


async def test_open_twice_is_rejected_and_close_is_idempotent():
    session = SimpleNamespace(close=AsyncMock())
    unit = UnitOfWork(SimpleNamespace(session_factory=lambda: session))
    async with unit:
        with pytest.raises(RuntimeError, match="already open"):
            await unit.open()
    await unit.close()
    session.close.assert_awaited_once()


async def test_closing_an_intermediate_scope_restores_open_ancestor():
    db = SimpleNamespace(
        session_factory=lambda: SimpleNamespace(close=AsyncMock())
    )
    async with UnitOfWork(db) as outer:
        middle = await UnitOfWork(db).open()
        inner = await UnitOfWork(db).open()
        await middle.close()
        assert UnitOfWork.current() is inner
        await inner.close()
        assert UnitOfWork.current() is outer
    assert UnitOfWork.current() is None


async def test_failed_open_does_not_replace_current_scope():
    def fail():
        raise RuntimeError("session factory failed")

    db = SimpleNamespace(
        session_factory=lambda: SimpleNamespace(close=AsyncMock())
    )
    async with UnitOfWork(db) as outer:
        failed = UnitOfWork(SimpleNamespace(session_factory=fail))
        with pytest.raises(RuntimeError, match="session factory failed"):
            await failed.open()
        assert not failed.is_open
        assert UnitOfWork.current() is outer


async def test_reopening_a_unit_creates_a_new_session():
    db = SimpleNamespace(
        session_factory=lambda: SimpleNamespace(close=AsyncMock())
    )
    unit = UnitOfWork(db)
    async with unit:
        first = unit.session
    async with unit:
        assert unit.session is not first
    first.close.assert_awaited_once()


async def test_flush_refresh_and_rollback_share_the_open_transaction(tmp_path):
    database = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/orm.db",
        2,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(UowRecord.__table__.create)
        async with database.uow() as unit:
            record = UowRecord()
            unit.session.add(record)
            await unit.flush()
            assert record.id is not None
            assert unit.in_transaction
            async with database.session_factory() as observer:
                assert (await observer.scalars(select(UowRecord))).all() == []
            stmt = (
                update(UowRecord)
                .values(name="stored")
                .execution_options(synchronize_session=False)
            )
            await unit.session.execute(stmt)
            assert record.name == "pending"
            await unit.refresh(record, attributes=["name"])
            assert record.name == "stored"
            await unit.rollback()
            assert not unit.in_transaction
        async with database.session_factory() as observer:
            assert (await observer.scalars(select(UowRecord))).all() == []
    finally:
        await database.dispose()


@pytest.mark.parametrize("cancellations", [1, 2])
async def test_cancellation_waits_for_session_cleanup(
    tmp_path, monkeypatch, cancellations
):
    import asyncio

    database = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/cancellation.db",
        1,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    closing = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    held = {}

    async def operation():
        try:
            async with database.uow() as unit:
                held["unit"] = unit
                session = unit.session
                real_close = session.close
                held["close"] = real_close

                async def delayed_close():
                    closing.set()
                    await release.wait()
                    await real_close()
                    closed.set()

                monkeypatch.setattr(session, "close", delayed_close)
                await session.execute(select(1))
        except asyncio.CancelledError:
            assert closed.is_set()
            assert UnitOfWork.current() is None
            raise

    task = asyncio.create_task(operation())
    try:
        await asyncio.wait_for(closing.wait(), 3)
        for _ in range(cancellations):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        assert database.engine.pool.checkedout() == 1
        assert held["unit"].is_open
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert closed.is_set()
        assert not held["unit"].is_open
        assert database.engine.pool.checkedout() == 0
        await held["unit"].close()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if "close" in held:
            await held["close"]()
        await database.dispose()


async def test_cleanup_cancellation_is_propagated_without_retrying():
    import asyncio

    session = SimpleNamespace(
        close=AsyncMock(side_effect=asyncio.CancelledError)
    )
    unit = UnitOfWork(SimpleNamespace(session_factory=lambda: session))
    with pytest.raises(asyncio.CancelledError):
        async with unit:
            pass
    session.close.assert_awaited_once()
    assert not unit.is_open
    assert UnitOfWork.current() is None


async def test_cleanup_failure_after_caller_cancellation_is_not_hidden():
    import asyncio

    closing = asyncio.Event()
    release = asyncio.Event()

    async def failing_close():
        closing.set()
        await release.wait()
        raise RuntimeError("cleanup failed")

    session = SimpleNamespace(close=failing_close)
    unit = UnitOfWork(SimpleNamespace(session_factory=lambda: session))

    async def operation():
        try:
            async with unit:
                pass
        finally:
            assert UnitOfWork.current() is None

    task = asyncio.create_task(operation())
    try:
        await asyncio.wait_for(closing.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await asyncio.wait_for(task, 3)
        assert not unit.is_open
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
