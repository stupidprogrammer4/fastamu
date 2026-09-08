import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.exceptions import ExitError

from fastamu.core.config import get_settings
from fastamu.core.provider import CoreProvider
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.uow import DBUnitOfWork, Rollback
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
    connection = cast(
        DBConnection, SimpleNamespace(session_factory=lambda: session)
    )

    class DatabaseProvider(Provider):
        @provide(scope=Scope.APP, override=True)
        def database(self) -> DBConnection:
            return connection

    container = make_async_container(provider, DatabaseProvider())
    try:
        yield SimpleNamespace(container=container, session=session)
    finally:
        await container.close()


async def test_success_commits_and_closes_the_session(transaction):
    async with transaction.container(scope=Scope.REQUEST) as scope:
        await scope.get(DBUnitOfWork)
        transaction.session.commit.assert_not_awaited()
    transaction.session.commit.assert_awaited_once()
    transaction.session.rollback.assert_not_awaited()
    transaction.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    "error", [ValueError("failed"), asyncio.CancelledError()]
)
async def test_scope_error_rolls_back_and_preserves_the_exception(
    transaction, error
):
    with pytest.raises(type(error)) as raised:
        async with transaction.container(scope=Scope.REQUEST) as scope:
            await scope.get(DBUnitOfWork)
            raise error
    assert raised.value is error
    transaction.session.rollback.assert_awaited_once()
    transaction.session.commit.assert_not_awaited()
    transaction.session.close.assert_awaited_once()


@pytest.mark.parametrize("operation", ["commit", "rollback"])
async def test_a_failed_transaction_operation_still_closes_the_session(
    transaction, operation
):
    getattr(transaction.session, operation).side_effect = RuntimeError(
        operation
    )
    with pytest.raises(ExitError):
        async with transaction.container(scope=Scope.REQUEST) as scope:
            await scope.get(DBUnitOfWork)
            if operation == "rollback":
                raise ValueError("failed")
    transaction.session.close.assert_awaited_once()


async def test_rollback_dependency_runs_before_each_resolution(transaction):
    async with transaction.container(scope=Scope.REQUEST) as scope:
        await scope.get(Rollback)
        transaction.session.rollback.assert_awaited_once()
        transaction.session.commit.assert_not_awaited()
        await scope.get(Rollback)
        assert transaction.session.rollback.await_count == 2
    transaction.session.close.assert_awaited_once()
