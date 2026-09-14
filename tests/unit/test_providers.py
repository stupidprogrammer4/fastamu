"""Explicit optional providers, typed scopes and installation suggestions."""

import importlib
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from dishka import Scope, make_async_container
from dishka.exceptions import NoFactoryError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from papilio.cli.app import app as cli
from papilio.core.config import DatabaseConfig, Settings
from papilio.infra.db import uow
from papilio.infra.db.connection import DBConnection
from papilio.providers import catalog, db
from papilio.scaffolding import project
from papilio.scaffolding.options import Infrastructure


def config(path):
    return DatabaseConfig(
        dsn=f"sqlite+aiosqlite:///{path}",
        test_dsn="",
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        pool_recycle=1800,
    )


@pytest.mark.parametrize(
    "prefix", ["PG", "MySQL", "MariaDB", "SQLite", "Oracle", "MSSQL"]
)
async def test_backend_provider_binds_typed_scopes_and_closes(
    prefix, tmp_path
):
    unit_type = getattr(uow, prefix + "UnitOfWork")
    provider = getattr(db, prefix + "Provider")(config(tmp_path / "db.sqlite"))
    # SQLite exercises the shared lifecycle, not six native database servers.
    container = make_async_container(provider)
    connection = await container.get(DBConnection[unit_type])
    dispose = AsyncMock(wraps=connection.dispose)
    connection.dispose = dispose
    try:
        with pytest.raises(ValueError, match="request failed"):
            async with container(scope=Scope.REQUEST) as scope:
                unit = await scope.get(unit_type)
                assert await scope.get(unit_type) is unit
                assert await scope.get(AsyncSession) is unit.session
                close = AsyncMock(wraps=unit.session.close)
                unit.session.close = close
                commit = AsyncMock(wraps=unit.session.commit)
                unit.session.commit = commit
                assert (await unit.execute(select(1))).scalar_one() == 1
                wrong_type = (
                    uow.MySQLUnitOfWork if prefix == "PG" else uow.PGUnitOfWork
                )
                with pytest.raises(NoFactoryError):
                    await scope.get(wrong_type)
                raise ValueError("request failed")
        close.assert_awaited_once()
        commit.assert_not_awaited()
        async with container(scope=Scope.REQUEST) as scope:
            other = await scope.get(unit_type)
            assert other is not unit
            assert other.connection is connection
            assert (await other.execute(select(2))).scalar_one() == 2
    finally:
        await container.close()
    dispose.assert_awaited_once()


async def test_two_database_components_do_not_share_sessions(tmp_path):
    container = make_async_container(
        *(
            db.SQLiteProvider(
                config(tmp_path / (name + ".sqlite"))
            ).to_component(name)
            for name in ("main", "reports")
        )
    )
    try:
        async with container(scope=Scope.REQUEST) as scope:
            main = await scope.get(uow.SQLiteUnitOfWork, component="main")
            reports = await scope.get(
                uow.SQLiteUnitOfWork, component="reports"
            )
            assert main.session is not reports.session
            assert main.connection is not reports.connection
            assert (
                await scope.get(AsyncSession, component="main") is main.session
            )
            assert (
                await scope.get(AsyncSession, component="reports")
                is reports.session
            )
            with pytest.raises(NoFactoryError):
                await scope.get(uow.SQLiteUnitOfWork)
    finally:
        await container.close()


@pytest.mark.parametrize(
    "name,resource",
    [("es", "ESClient"), ("redis", "RedisClient"), ("http", "HTTPConnection")],
)
async def test_client_providers_are_lazy_and_close_once(
    name, resource, monkeypatch
):
    spec = next(item for item in catalog.PROVIDERS if item.name == name)
    module = importlib.import_module("papilio.providers." + spec.module)
    resource_type = getattr(module, resource)
    settings = Settings.model_validate(
        yaml.safe_load(
            project.files(
                "shop",
                "Shop",
                infra=[
                    Infrastructure.ES,
                    Infrastructure.REDIS,
                    Infrastructure.HTTP,
                ],
            )["config.yml"]
        )
    )
    client = SimpleNamespace(close=AsyncMock())
    constructor = Mock(return_value=client)
    monkeypatch.setattr(module, resource, constructor)
    container = make_async_container(
        getattr(module, spec.cls)(getattr(settings, name))
    )
    constructor.assert_not_called()
    try:
        assert await container.get(resource_type) is client
        assert await container.get(resource_type) is client
        constructor.assert_called_once()
    finally:
        await container.close()
    client.close.assert_awaited_once()


def test_provider_catalog_reports_installation_and_explicit_usage(monkeypatch):
    def version(name):
        if name in ("asyncmy", "throttled-py"):
            raise PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(catalog, "version", version)
    runner = CliRunner()
    result = runner.invoke(cli, ["providers"])
    assert result.exit_code == 0, result.output
    assert "MySQLProvider" in result.output and "asyncmy" in result.output
    result = runner.invoke(cli, ["providers", "mysql"])
    assert result.exit_code == 0, result.output
    assert "pip install 'papilio[mysql]'" in result.output
    assert "from papilio.providers.db import MySQLProvider" in result.output
    assert "MySQLProvider(settings.db)" in result.output
    result = runner.invoke(cli, ["providers", "rate-redis"])
    assert "RedisProvider(settings.redis)" in result.output
    assert "RedisRateProvider()" in result.output
    assert runner.invoke(cli, ["providers", "missing"]).exit_code != 0


def test_scaffold_selects_optional_providers_and_es_startup_explicitly():
    plain = project.files("shop", "Shop")["shop/main.py"]
    assert "papilio.providers" not in plain
    assert "boot_es_indices" not in plain
    selected = project.files(
        "shop", "Shop", infra=[Infrastructure.ES, Infrastructure.RATE_LIMIT]
    )["shop/main.py"]
    assert "papilio.providers.es import ESProvider" in selected
    assert "papilio.providers.redis import RedisProvider" not in selected
    assert (
        "papilio.providers.rate_limit.memory import MemoryRateProvider"
        in selected
    )
    assert "boot_es_indices" in selected and "lifespan=lifespan" in selected
    assert "PGProvider" not in selected
