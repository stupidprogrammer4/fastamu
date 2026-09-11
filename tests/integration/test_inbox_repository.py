import asyncio
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import DeclarativeBase

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.dialects import DIALECTS
from fastamu.infra.db.dialects.sqlite import SQLiteDialect
from fastamu.infra.db.inbox import repository
from fastamu.infra.db.inbox.repository import InboxRepository


class Base(DeclarativeBase):
    pass


class Receipt(Base):
    __tablename__ = "insert_once_receipt"
    consumer = Column(String(64), primary_key=True)
    message_id = Column(String(64), primary_key=True)
    value = Column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("message_id <> 'invalid'"),
        UniqueConstraint("message_id"),
    )


class Pending(Base):
    __tablename__ = "insert_once_pending"
    id = Column(Integer, primary_key=True)
    value = Column(Integer, nullable=False)


class SQLiteFallback(SQLiteDialect):
    def insert_if_absent(self, table, values, keys):
        return None


@pytest.fixture(
    params=["postgresql", "mysql", "sqlite", "fallback", "unknown"]
)
async def runtime(request, tmp_path, monkeypatch):
    backend = request.param
    monkeypatch.setattr(repository, "inbox", Receipt.__table__)
    if backend in ("fallback", "unknown"):
        if backend == "fallback":
            monkeypatch.setitem(DIALECTS, "sqlite", SQLiteFallback)
        else:
            monkeypatch.delitem(DIALECTS, "sqlite")
    url = (
        os.getenv(f"FASTAMU_TEST_{backend.upper()}")
        if backend in ("postgresql", "mysql")
        else f"sqlite+aiosqlite:///{tmp_path}/insert.db"
    )
    if not url:
        pytest.skip(f"Set FASTAMU_TEST_{backend.upper()}")
    db = DBConnection(url, 5, 0, 5, 1800)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield SimpleNamespace(db=db, backend=backend, statements=statements)
    finally:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await db.dispose()


async def claim(session, id="same"):
    return await InboxRepository(session).claim("apply", id)


async def test_duplicate_keeps_original_values_and_transaction(runtime):
    async with runtime.db.session_factory.begin() as session:
        runtime.statements.clear()
        assert await claim(session)
        if runtime.backend in ("postgresql", "sqlite"):
            assert len(runtime.statements) == 1
            assert "ON CONFLICT" in runtime.statements[0]
        await session.execute(Receipt.__table__.update().values(value=99))
        assert not await claim(session)
        assert await claim(session, "another")
        assert (
            await session.scalar(
                select(Receipt.value).where(Receipt.message_id == "same")
            )
            == 99
        )


async def test_rollback_releases_identity(runtime):
    with pytest.raises(ValueError, match="rollback"):
        async with runtime.db.session_factory.begin() as session:
            assert await claim(session)
            raise ValueError("rollback")
    async with runtime.db.session_factory.begin() as session:
        assert await claim(session)


async def test_concurrent_deliveries_have_one_winner(runtime):
    async def receive():
        async with runtime.db.session_factory.begin() as session:
            return await claim(session)

    assert sum(await asyncio.gather(*(receive() for _ in range(5)))) == 1


@pytest.mark.parametrize("rollback", [False, True])
async def test_claim_waits_for_owner_commit_or_rollback(runtime, rollback):
    started = asyncio.Event()

    async def competitor():
        async with runtime.db.session_factory.begin() as session:
            started.set()
            return await claim(session)

    async with runtime.db.session_factory() as owner:
        await owner.begin()
        assert await claim(owner)
        task = asyncio.create_task(competitor())
        try:
            await asyncio.wait_for(started.wait(), 5)
            await asyncio.sleep(0.05)
            assert not task.done()
        finally:
            await owner.rollback() if rollback else await owner.commit()
            result = await asyncio.wait_for(task, 5)
        assert result is rollback


@pytest.mark.parametrize(
    "consumer,message_id",
    [(None, "different"), ("apply", "invalid"), ("other", "same")],
)
async def test_other_integrity_errors_propagate(runtime, consumer, message_id):
    async with runtime.db.session_factory.begin() as session:
        assert await claim(session)
    with pytest.raises(DBAPIError):
        async with runtime.db.session_factory.begin() as session:
            await InboxRepository(session).claim(consumer, message_id)


async def test_does_not_flush_pending_orm_changes(runtime):
    async with runtime.db.session_factory.begin() as session:
        pending = Pending(id=1, value=42)
        session.add(pending)
        assert await claim(session)
        assert pending in session.new
        assert not await claim(session)
        assert pending in session.new
    async with runtime.db.session_factory() as session:
        assert await session.scalar(select(Pending.value)) == 42


@pytest.mark.parametrize("runtime", ["mysql"], indirect=True)
async def test_mysql_duplicate_is_visible_after_snapshot(runtime):
    async with runtime.db.session_factory.begin() as observer:
        assert (await observer.execute(select(Receipt))).first() is None
        async with runtime.db.session_factory.begin() as owner:
            assert await claim(owner)
        assert not await claim(observer)


async def test_requires_existing_transaction(runtime):
    async with runtime.db.session_factory() as session:
        with pytest.raises(RuntimeError, match="active transaction"):
            await claim(session)


@pytest.mark.parametrize(
    "runtime", ["mysql", "sqlite", "fallback", "unknown"], indirect=True
)
async def test_case_insensitive_collision_is_not_an_exact_duplicate(
    runtime, monkeypatch
):
    collation = (
        "utf8mb4_0900_ai_ci" if runtime.backend == "mysql" else "NOCASE"
    )
    folded = Table(
        "insert_once_folded",
        MetaData(),
        Column("consumer", String(64), primary_key=True),
        Column(
            "message_id", String(64, collation=collation), primary_key=True
        ),
    )
    async with runtime.db.engine.begin() as connection:
        await connection.run_sync(folded.create)
    monkeypatch.setattr(repository, "inbox", folded)
    try:
        async with runtime.db.session_factory.begin() as session:
            assert await claim(session, "message")
        with pytest.raises((IntegrityError, ValueError)):
            async with runtime.db.session_factory.begin() as session:
                await claim(session, "MESSAGE")
    finally:
        async with runtime.db.engine.begin() as connection:
            await connection.run_sync(folded.drop)
