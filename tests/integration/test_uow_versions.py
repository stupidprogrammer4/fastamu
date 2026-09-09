import asyncio
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.tables import ProjectionVersionTable
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.infra.db.versions import (
    ProjectionExpired,
    ProjectionObsolete,
    ProjectionPending,
)


@pytest.fixture(
    params=["sqlite", "postgresql", "mysql", "mariadb", "mssql", "oracle"]
)
async def database(request, tmp_path):
    name = request.param
    dsn = (
        f"sqlite+aiosqlite:///{tmp_path}/versions.sqlite"
        if name == "sqlite"
        else os.environ.get("FASTAMU_TEST_" + name.upper())
    )
    if not dsn:
        pytest.skip(f"Set FASTAMU_TEST_{name.upper()} for live {name} tests")
    db = DBConnection(dsn, 4, 0, 5, 1800)
    table = ProjectionVersionTable.__table__
    async with db.engine.begin() as connection:
        await connection.run_sync(table.create, checkfirst=True)
    projection = type("Projection_" + uuid4().hex, (), {})
    try:
        yield db, projection
    finally:
        async with db.engine.begin() as connection:
            await connection.execute(
                delete(table).where(
                    table.c.projection
                    == f"{projection.__module__}.{projection.__qualname__}"
                )
            )
        await db.dispose()


async def stage(projection, ids=None):
    ticket = await DBUnitOfWork.stage_projection(
        projection, ids or [7], time.time() + 10800
    )
    assert ticket is not None
    return ticket


async def test_commit_visibility_and_completion(database):
    db, projection = database
    async with DBUnitOfWork(db):
        ticket = await stage(projection)
        async with DBUnitOfWork(db):
            with pytest.raises(ProjectionPending):
                await DBUnitOfWork.pending_projection(ticket)
    async with DBUnitOfWork(db):
        pending = await DBUnitOfWork.pending_projection(ticket)
        await DBUnitOfWork.complete_projection(pending)
    async with DBUnitOfWork(db):
        with pytest.raises(ProjectionObsolete):
            await DBUnitOfWork.pending_projection(ticket)


async def test_rollback_revision_reuse_does_not_validate_old_message(database):
    db, projection = database
    async with DBUnitOfWork(db) as unit:
        rolled_back = await stage(projection)
        await unit.rollback()
    async with DBUnitOfWork(db):
        with pytest.raises(ProjectionPending):
            await DBUnitOfWork.pending_projection(rolled_back)
    async with DBUnitOfWork(db):
        committed = await stage(projection)
    assert (
        committed.entries[0].last_version
        == rolled_back.entries[0].last_version
    )
    assert committed.entries[0].version_id != rolled_back.entries[0].version_id
    async with DBUnitOfWork(db):
        with pytest.raises(ProjectionObsolete):
            await DBUnitOfWork.pending_projection(rolled_back)
        assert await DBUnitOfWork.pending_projection(committed) == committed


async def test_older_completion_cannot_complete_a_new_version(database):
    db, projection = database
    async with DBUnitOfWork(db):
        old = await stage(projection)
    async with DBUnitOfWork(db):
        new = await stage(projection)
    async with DBUnitOfWork(db):
        await DBUnitOfWork.complete_projection(old)
    async with DBUnitOfWork(db):
        assert await DBUnitOfWork.pending_projection(new) == new
        with pytest.raises(ProjectionObsolete):
            await DBUnitOfWork.pending_projection(old)


async def test_batch_keeps_current_targets_when_some_are_superseded(
    database,
):
    db, projection = database
    async with DBUnitOfWork(db):
        batch = await stage(projection, [7, 8, 7])
    async with DBUnitOfWork(db):
        await stage(projection, [7])
    async with DBUnitOfWork(db):
        remaining = await DBUnitOfWork.pending_projection(batch)
        assert [entry.target_id for entry in remaining.entries] == [8]
        await DBUnitOfWork.complete_projection(remaining)
    async with DBUnitOfWork(db):
        with pytest.raises(ProjectionObsolete):
            await DBUnitOfWork.pending_projection(batch)


async def test_expired_version_is_retained_and_can_be_replaced(database):
    db, projection = database
    async with DBUnitOfWork(db):
        ticket = await DBUnitOfWork.stage_projection(
            projection, [7], time.time() - 1
        )
        assert ticket is not None
    async with DBUnitOfWork(db):
        with pytest.raises(ProjectionExpired):
            await DBUnitOfWork.pending_projection(ticket)
    async with DBUnitOfWork(db):
        fresh = await stage(projection)
    assert fresh.entries[0].last_version > ticket.entries[0].last_version


async def test_concurrent_first_publishers_get_distinct_ordered_versions(
    database,
):
    db, projection = database
    ready = asyncio.Event()
    release = asyncio.Event()

    async def first():
        async with DBUnitOfWork(db):
            ticket = await stage(projection)
            ready.set()
            await release.wait()
        return ticket

    async def second():
        await ready.wait()
        async with DBUnitOfWork(db):
            return await stage(projection)

    one = asyncio.create_task(first())
    two = asyncio.create_task(second())
    await asyncio.wait_for(ready.wait(), 5)
    await asyncio.sleep(0.05)
    release.set()
    try:
        old, new = await asyncio.wait_for(asyncio.gather(one, two), 10)
        assert new.entries[0].last_version > old.entries[0].last_version
    finally:
        one.cancel()
        two.cancel()
        await asyncio.gather(one, two, return_exceptions=True)


@pytest.mark.parametrize(
    "dialect",
    [
        postgresql.dialect(),
        mysql.dialect(),
        sqlite.dialect(),
        mssql.dialect(),
        oracle.dialect(),
    ],
)
def test_version_schema_compiles_for_each_database_family(dialect):
    ddl = str(
        CreateTable(ProjectionVersionTable.__table__).compile(dialect=dialect)
    )
    assert "fastamu_projection_versions" in ddl
    assert "last_version" in ddl
