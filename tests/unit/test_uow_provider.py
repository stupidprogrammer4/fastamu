import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide

from papilio.core.config import get_settings
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import PGUnitOfWork
from papilio.providers.db import PGProvider
from papilio.testing.fixtures import core_provider_of


@pytest.fixture(params=["runtime", "testing"])
def provider(request):
    if request.param == "runtime":
        return PGProvider(get_settings().db)
    return core_provider_of(get_settings())


@pytest.fixture
async def transaction(provider):
    session = SimpleNamespace(
        commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock()
    )
    stub = SimpleNamespace(session_factory=lambda: session)
    stub.uow = lambda: PGUnitOfWork(cast(DBConnection[PGUnitOfWork], stub))
    connection = cast(DBConnection[PGUnitOfWork], stub)

    class DatabaseProvider(Provider):
        @provide(scope=Scope.APP, override=True)
        def database(self) -> DBConnection[PGUnitOfWork]:
            return connection

    container = make_async_container(provider, DatabaseProvider())
    try:
        yield SimpleNamespace(container=container, session=session)
    finally:
        await container.close()


async def test_scope_closes_without_committing(transaction):
    async with transaction.container(scope=Scope.REQUEST) as scope:
        await scope.get(PGUnitOfWork)
    transaction.session.commit.assert_not_awaited()
    transaction.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error", [ValueError("failed"), asyncio.CancelledError()]
)
async def test_scope_error_preserves_exception_and_closes(transaction, error):
    with pytest.raises(type(error)) as raised:
        async with transaction.container(scope=Scope.REQUEST) as scope:
            await scope.get(PGUnitOfWork)
            raise error
    assert raised.value is error
    transaction.session.commit.assert_not_awaited()
    transaction.session.close.assert_awaited_once()


async def test_provider_disposes_database_on_container_close(
    provider, tmp_path, monkeypatch
):
    from sqlalchemy import select

    from papilio.core.config import Settings

    settings = get_settings().model_copy(deep=True)
    settings.db.dsn = f"sqlite+aiosqlite:///{tmp_path}/provider.db"

    class SettingsProvider(Provider):
        @provide(scope=Scope.APP, override=True)
        def settings(self) -> Settings:
            return settings

    if isinstance(provider, PGProvider):
        provider.config = settings.db
        container = make_async_container(provider)
    else:
        container = make_async_container(provider, SettingsProvider())
    database = await container.get(DBConnection[PGUnitOfWork])
    original_dispose = database.dispose
    dispose = AsyncMock(wraps=original_dispose)
    monkeypatch.setattr(database, "dispose", dispose)
    try:
        async with container(scope=Scope.REQUEST) as scope:
            unit = await scope.get(PGUnitOfWork)
            await unit.session.execute(select(1))
        await container.close()
        dispose.assert_awaited_once()
    finally:
        await container.close()
        await original_dispose()
