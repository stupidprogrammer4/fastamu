"""Smoke integration test — runs alembic migrations on the test DB (`test_dsn`)
and talks to it through the unit of work. Marked `integration` by path."""

import pytest

from fastamu.infra.db.uow import DBUnitOfWork


@pytest.mark.usefixtures("migrated_test_db")
async def test_database_is_migrated_and_reachable(uow: DBUnitOfWork) -> None:
    now = await uow.now()
    assert now is not None
