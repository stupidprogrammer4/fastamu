"""Typed repository dependencies and native Dishka database scopes."""

import importlib
import inspect
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.exceptions import GraphMissingFactoryError, NoFactoryError
from sqlmodel import Field

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.schema.entity import BaseEntity
from papilio.infra.db.repositories.backends.postgresql import (
    PGRepository,
)
from papilio.infra.db.repositories.backends.sqlite import (
    SQLiteRepository,
)
from papilio.infra.db.repositories.contracts.base import RepositoryContract
from papilio.infra.db.repositories.contracts.sqlite import (
    SQLiteRepositoryContract,
)
from papilio.infra.db.table import BaseTable
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork


class BindingEntity(BaseEntity):
    key: int = Field(primary_key=True)


class BindingTable(BindingEntity, BaseTable, table=True):
    pass


class BindingRepository(SQLiteRepository[BindingEntity]):
    table = BindingTable


class BindingProvider(Provider):
    repository = provide(
        BindingRepository,
        provides=SQLiteRepositoryContract[BindingEntity],
        scope=Scope.REQUEST,
    )


@pytest.mark.parametrize(
    "backend,prefix",
    [
        ("postgresql", "PG"),
        ("mysql", "MySQL"),
        ("mariadb", "MariaDB"),
        ("sqlite", "SQLite"),
        ("oracle", "Oracle"),
        ("mssql", "MSSQL"),
    ],
)
@pytest.mark.parametrize(
    "shape", ["", "Identified", "Timestamp", "Persistence"]
)
def test_each_implementation_fulfills_its_own_contract(backend, prefix, shape):
    contracts = importlib.import_module(
        f"papilio.infra.db.repositories.contracts.{backend}"
    )
    implementations = importlib.import_module(
        f"papilio.infra.db.repositories.backends.{backend}"
    )
    units = importlib.import_module("papilio.infra.db.uow")
    name = f"{prefix}{shape}Repository"
    contract = getattr(contracts, name + "Contract")
    implementation = getattr(implementations, name)
    assert inspect.isabstract(contract)
    assert not inspect.isabstract(implementation)
    assert issubclass(implementation, contract)
    assert issubclass(contract, RepositoryContract)
    signature = inspect.signature(implementation.__init__)
    assert signature.parameters["uow"].annotation is getattr(
        units, prefix + "UnitOfWork"
    )
    assert not hasattr(implementation, "validate")
    if backend in ("oracle", "mssql"):
        assert not hasattr(contract, "upsert")
        assert not hasattr(contract, "bulk_upsert")


def test_incomplete_contract_cannot_be_instantiated():
    class Incomplete(SQLiteRepositoryContract[BindingEntity]):
        table = BindingTable

    with pytest.raises(TypeError, match="abstract"):
        Incomplete()


@pytest.fixture
async def databases(tmp_path):
    connections = [
        DBConnection(
            f"sqlite+aiosqlite:///{tmp_path}/{name}.db",
            2,
            0,
            5,
            1800,
            uow_factory=SQLiteUnitOfWork,
        )
        for name in ("main", "reporting")
    ]
    try:
        for database in connections:
            async with database.engine.begin() as connection:
                await connection.run_sync(BindingTable.__table__.create)
        yield connections
    finally:
        for database in connections:
            await database.dispose()


def connection_provider(database, component):
    class ConnectionProvider(Provider):
        @provide(scope=Scope.APP)
        async def connection(
            self,
        ) -> AsyncIterator[DBConnection[SQLiteUnitOfWork]]:
            try:
                yield database
            finally:
                await database.dispose()

        @provide(scope=Scope.REQUEST)
        async def uow(
            self, connection: DBConnection[SQLiteUnitOfWork]
        ) -> AsyncIterator[SQLiteUnitOfWork]:
            async with connection.uow() as unit:
                yield unit

    return ConnectionProvider(component=component)


async def test_named_bindings_share_only_their_own_session(
    databases, monkeypatch
):
    providers = []
    for name, database in zip(("main", "reporting"), databases, strict=True):
        providers.extend(
            (
                connection_provider(database, name),
                BindingProvider(component=name),
            )
        )
    container = make_async_container(*providers)
    try:
        async with container(scope=Scope.REQUEST) as scope:
            main = await scope.get(
                SQLiteRepositoryContract[BindingEntity], component="main"
            )
            reporting = await scope.get(
                SQLiteRepositoryContract[BindingEntity], component="reporting"
            )
            main_unit = await scope.get(SQLiteUnitOfWork, component="main")
            reporting_unit = await scope.get(
                SQLiteUnitOfWork, component="reporting"
            )
            assert main.uow.session is main_unit.session
            assert reporting.uow.session is reporting_unit.session
            assert main.uow.session is not reporting.uow.session
            assert main.uow.session.bind is databases[0].engine
            assert reporting.uow.session.bind is databases[1].engine
            close_main = AsyncMock(wraps=main.uow.session.close)
            close_reporting = AsyncMock(wraps=reporting.uow.session.close)
            monkeypatch.setattr(main.uow.session, "close", close_main)
            monkeypatch.setattr(
                reporting.uow.session, "close", close_reporting
            )
            with pytest.raises(NoFactoryError):
                await scope.get(SQLiteRepositoryContract[BindingEntity])

            # Reporting was resolved last; explicitly select main for commit.
            assert UnitOfWork.current() is reporting_unit
            async with transaction(main_unit):
                assert UnitOfWork.current() is main_unit
                await main.create(BindingEntity(key=1))
                async with transaction():
                    assert UnitOfWork.current() is main_unit
            assert UnitOfWork.current() is reporting_unit
            await reporting.create(BindingEntity(key=2))

        close_main.assert_awaited_once()
        close_reporting.assert_awaited_once()
        assert UnitOfWork.current() is None
        async with container(scope=Scope.REQUEST) as scope:
            main = await scope.get(
                SQLiteRepositoryContract[BindingEntity], component="main"
            )
            reporting = await scope.get(
                SQLiteRepositoryContract[BindingEntity], component="reporting"
            )
            assert [row.key for row in await main.get_all()] == [1]
            assert await reporting.get_all() == []
    finally:
        await container.close()


async def test_wrong_backend_fails_when_building_container(databases):
    class WrongRepository(PGRepository[BindingEntity]):
        table = BindingTable

    class WrongProvider(Provider):
        repository = provide(WrongRepository, scope=Scope.REQUEST)

    # No custom validation: PGUnitOfWork has no registered factory.
    with pytest.raises(GraphMissingFactoryError, match="PGUnitOfWork"):
        make_async_container(
            connection_provider(databases[0], ""), WrongProvider()
        )
