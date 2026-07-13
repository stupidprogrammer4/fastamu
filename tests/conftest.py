from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from alembic import command
from alembic.config import Config
from dishka import Provider, Scope, make_async_container, provide
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from taskiq import ScheduledTask, ScheduleSource

import src.tasks.broker  # noqa: F401

from src.core.bootstrap import get_bootstrapper
from src.core.config import Settings
from src.infra.es.client import ESClient
from src.infra.postgres.connection import PGConnection
from src.infra.postgres.uow import PGUnitOfWork
from src.infra.redis.client import RedisClient


class _NullScheduleSource(ScheduleSource):
    """Hermetic schedule source for tests — never touches redis."""

    async def get_schedules(self) -> list[ScheduledTask]:
        return []

    async def add_schedule(self, schedule: ScheduledTask) -> None: ...

    async def delete_schedule(self, schedule_id: str) -> None: ...


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests by their folder: tests/unit -> unit, tests/integration -> integration."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)


def obj(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


@pytest.fixture
def make_obj():
    return obj


# --- integration: real test database --------------------------------------------

def _load_settings() -> Settings:
    path = Path("config.yml")
    if not path.exists():
        raise ValueError("config.yml not found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Settings.model_validate(raw)


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    settings = _load_settings()
    if settings is None:
        pytest.skip("integration tests require config.yml with postgresql.test_dsn")
    return settings


@pytest.fixture(scope="session")
def test_dsn(integration_settings: Settings) -> str:
    return integration_settings.postgresql.test_dsn


@pytest.fixture(scope="session")
def migrated_test_db(test_dsn: str) -> Iterator[None]:
    db_name = make_url(test_dsn).database or ""
    if "test" not in db_name:
        pytest.skip(f"refusing to reset non-test database {db_name!r}")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_dsn)
    try:
        asyncio.run(_reset_public_schema(test_dsn))
        command.upgrade(cfg, "head")
    except (OSError, OperationalError) as exc:
        pytest.skip(f"integration test database is not reachable: {exc}")
    yield
    try:
        command.downgrade(cfg, "base")
    except (OSError, OperationalError):
        pass


async def _reset_public_schema(dsn: str) -> None:
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture
async def pg(test_dsn: str) -> AsyncIterator[PGConnection]:
    connection = PGConnection(
        dsn=test_dsn,
        pool_size=1,
        max_overflow=0,
        pool_timeout=30,
        pool_recycle=1800,
    )
    try:
        yield connection
    finally:
        await connection.dispose()


@pytest.fixture
async def uow(pg: PGConnection) -> AsyncIterator[PGUnitOfWork]:
    async with PGUnitOfWork(pg) as unit:
        yield unit


@pytest.fixture
async def es(integration_settings: Settings) -> AsyncIterator[ESClient]:
    client = ESClient(
        integration_settings.es.hosts,
        username=integration_settings.es.username,
        password=integration_settings.es.password,
        api_key=integration_settings.es.api_key,
        verify_certs=integration_settings.es.verify_certs,
        ca_certs=integration_settings.es.ca_certs,
    )
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def clean_db(pg: PGConnection) -> None:
    """Truncate every mapped table (discovered from the modules) between tests."""
    get_bootstrapper().boot_sqlmodels()
    tables = list(reversed(SQLModel.metadata.sorted_tables))
    if not tables:
        return
    async with pg.session_factory() as session:
        for table in tables:
            await session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        await session.commit()


@pytest.fixture
async def dishka_container(integration_settings: Settings, test_dsn: str):
    test_settings = integration_settings.model_copy(
        deep=True,
        update={"postgresql": integration_settings.postgresql.model_copy(update={"dsn": test_dsn})},
    )

    class TestCoreProvider(Provider):
        @provide(scope=Scope.APP)
        def settings(self) -> Settings:
            return test_settings

        @provide(scope=Scope.APP)
        def postgresql(self, settings: Settings) -> PGConnection:
            return PGConnection(
                dsn=settings.postgresql.dsn,
                pool_size=2,
                max_overflow=1,
                pool_timeout=settings.postgresql.pool_timeout,
                pool_recycle=settings.postgresql.pool_recycle,
            )

        @provide(scope=Scope.REQUEST)
        async def uow(self, pg: PGConnection) -> AsyncIterator[PGUnitOfWork]:
            async with PGUnitOfWork(pg) as unit:
                yield unit

        @provide(scope=Scope.APP)
        def schedule_source(self) -> ScheduleSource:
            return _NullScheduleSource()

        @provide(scope=Scope.APP)
        async def es(self, settings: Settings) -> AsyncIterator[ESClient]:
            client = ESClient(
                settings.es.hosts,
                username=settings.es.username,
                password=settings.es.password,
                api_key=settings.es.api_key,
                verify_certs=settings.es.verify_certs,
                ca_certs=settings.es.ca_certs,
            )
            try:
                yield client
            finally:
                await client.close()

        @provide(scope=Scope.APP)
        async def redis(self, settings: Settings) -> AsyncIterator[RedisClient]:
            client = RedisClient(
                settings.redis.url,
                max_connections=settings.redis.max_connections,
                socket_timeout=settings.redis.socket_timeout,
                socket_connect_timeout=settings.redis.socket_connect_timeout,
                health_check_interval=settings.redis.health_check_interval,
            )
            try:
                yield client
            finally:
                await client.close()

    # Module providers are discovered automatically — new modules need no edit here.
    container = make_async_container(TestCoreProvider(), *get_bootstrapper().boot_providers())
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def dishka_request(dishka_container):
    async with dishka_container(scope=Scope.REQUEST) as request_container:
        yield request_container
