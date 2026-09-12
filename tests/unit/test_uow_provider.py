import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide

from fastamu.core.config import get_settings
from fastamu.core.provider import CoreProvider
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.uow import DBUnitOfWork, ReturningUnitOfWork
from fastamu.testing.fixtures import core_provider_of


@pytest.fixture(params=["runtime", "testing"])
def provider(request):
    if request.param == "runtime":
        return CoreProvider()
    return core_provider_of(get_settings())


@pytest.fixture
async def transaction(provider):
    session = SimpleNamespace(
        commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock()
    )
    stub = SimpleNamespace(session_factory=lambda: session)
    stub.uow = lambda: ReturningUnitOfWork(cast(DBConnection, stub))
    connection = cast(DBConnection, stub)

    class DatabaseProvider(Provider):
        @provide(scope=Scope.APP, override=True)
        def database(self) -> DBConnection:
            return connection

    container = make_async_container(provider, DatabaseProvider())
    try:
        yield SimpleNamespace(container=container, session=session)
    finally:
        await container.close()


async def test_scope_closes_without_committing(transaction):
    async with transaction.container(scope=Scope.REQUEST) as scope:
        await scope.get(DBUnitOfWork)
    transaction.session.commit.assert_not_awaited()
    transaction.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error", [ValueError("failed"), asyncio.CancelledError()]
)
async def test_scope_error_preserves_exception_and_closes(transaction, error):
    with pytest.raises(type(error)) as raised:
        async with transaction.container(scope=Scope.REQUEST) as scope:
            await scope.get(DBUnitOfWork)
            raise error
    assert raised.value is error
    transaction.session.commit.assert_not_awaited()
    transaction.session.close.assert_awaited_once()
