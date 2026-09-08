"""The test harness, as a pytest plugin.

Installed with the package and registered under `pytest11`, so every fixture
here is available in any project that depends on Fastamu — no conftest to copy,
and no drift between the framework's own suite and yours.

The container these fixtures build is the **real** one: module providers are
discovered exactly as in production, only pointed at the test database with a
schedule source that never reaches redis. So a test exercises your wiring, not
a rehearsal of it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from alembic import command
from alembic.config import Config
from asyncpg.exceptions import PostgresError
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, delete
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from taskiq import ScheduledTask, ScheduleSource

from fastamu.common.security.passwords import PasswordHasher
from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import Settings
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.uow import DBUnitOfWork, rollback_transaction
from fastamu.infra.es.client import ESClient
from fastamu.infra.http.connection import HTTPConnection
from fastamu.infra.redis.client import RedisClient
from fastamu.web.ratelimit import RateLimitProvider


class _NullScheduleSource(ScheduleSource):
    """Hermetic schedule source for tests — never touches redis."""

    async def get_schedules(self) -> list[ScheduledTask]:
        return []

    async def add_schedule(self, schedule: ScheduledTask) -> None: ...

    async def delete_schedule(self, schedule_id: str) -> None: ...


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark tests by their folder: tests/unit -> unit, tests/integration
    -> integration."""
    folders = {
        "/tests/integration/": pytest.mark.integration,
        "/tests/unit/": pytest.mark.unit,
        "/tests/api/": pytest.mark.api,
    }
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        for folder, mark in folders.items():
            if folder in path:
                item.add_marker(mark)


def obj(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


@pytest.fixture
def make_obj():
    return obj


# --- integration: real test database ----------------------------------------


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
        pytest.skip("integration tests require config.yml with db.test_dsn")
    return settings


@pytest.fixture(scope="session")
def test_dsn(integration_settings: Settings) -> str:
    return integration_settings.db.test_dsn


@pytest.fixture(scope="session")
def migrated_test_db(test_dsn: str) -> Iterator[None]:
    db_name = make_url(test_dsn).database or ""
    if "test" not in db_name:
        pytest.skip(f"refusing to reset non-test database {db_name!r}")

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_dsn)
    # only reaching the database is allowed to skip; a migration that fails
    # once we're connected is a real failure and must be reported as one
    try:
        asyncio.run(_reset_test_schema(test_dsn))
    except _UNREACHABLE as exc:
        pytest.skip(f"integration test database is not reachable: {exc}")
    command.upgrade(cfg, "head")
    yield
    try:
        command.downgrade(cfg, "base")
    except _UNREACHABLE:
        pass


# a bad host, a refused connection and a rejected password all mean the same
# thing here: there is no test database to run against. asyncpg raises its own
# errors straight out of connect, so neither OSError nor SQLAlchemyError alone
# covers them.
_UNREACHABLE = (OSError, SQLAlchemyError, PostgresError)


async def _reset_test_schema(dsn: str) -> None:
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                from fastamu.infra.db.dialects.postgresql import reset_schema

                await reset_schema(conn)
            else:
                metadata = MetaData()
                await conn.run_sync(metadata.reflect)
                await conn.run_sync(metadata.drop_all)

    finally:
        await engine.dispose()


@pytest.fixture
async def pg(test_dsn: str) -> AsyncIterator[DBConnection]:
    connection = DBConnection(
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
async def uow(pg: DBConnection) -> AsyncIterator[DBUnitOfWork]:
    async with DBUnitOfWork(pg) as unit:
        yield unit


@pytest.fixture
async def es(integration_settings: Settings) -> AsyncIterator[ESClient]:
    if integration_settings.es is None:
        pytest.skip("Elasticsearch is disabled")
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
async def clean_db(pg: DBConnection, es: ESClient) -> None:
    """Empty every mapped table and read-model index (both discovered from the
    modules) between tests."""
    bootstrapper = get_bootstrapper()
    bootstrapper.boot_sqlmodels()
    tables = list(reversed(SQLModel.metadata.sorted_tables))
    if tables:
        async with pg.session_factory() as session:
            if pg.dialect.name == "postgresql":
                from fastamu.infra.db.dialects.postgresql import (
                    truncate_tables,
                )

                await truncate_tables(session, tables)
            else:
                for table in tables:
                    await session.execute(delete(table))
            await session.commit()
    # a projection outlives the row it came from, so a stale document would
    # answer the next test's search
    for document in bootstrapper.boot_documents():
        index = document.Index.name
        if await es.client.indices.exists(index=index):
            await es.client.delete_by_query(
                index=index,
                body={"query": {"match_all": {}}},
                refresh=True,
                conflicts="proceed",
            )


def test_settings_of(settings: Settings, test_dsn: str) -> Settings:
    """The settings a test runs under: the test database, and no rate limits.

    Limits are off by default because a suite hits the same routes far faster
    than any real client, and a test failing on a budget it never meant to
    exercise teaches nothing. A test *about* limiting turns them back on for
    itself — the guards read whichever settings their container holds.

    Args:
        settings (Settings): The settings loaded from config.yml.
        test_dsn (str): The test database to point at.
    Returns:
        (Settings): A copy safe to run a suite against.
    """
    return settings.model_copy(
        deep=True,
        update={
            "db": settings.db.model_copy(update={"dsn": test_dsn}),
            "rate_limit": settings.rate_limit.model_copy(
                update={"enabled": False}
            ),
        },
    )


def core_provider_of(test_settings: Settings) -> Provider:
    """The infra layer, wired for a test: the test database on a small pool, a
    schedule source that never reaches redis, and everything else as in
    production.

    A function rather than a fixture so an API-level conftest can build its own
    container from the same wiring, instead of copying it.

    Args:
        test_settings (Settings): What the container should be built on.
    Returns:
        (Provider): The provider to hand to `make_async_container`.
    """

    class TestCoreProvider(Provider):
        rollback = provide(
            staticmethod(rollback_transaction),
            scope=Scope.REQUEST,
            cache=False,
        )

        @provide(scope=Scope.APP)
        def settings(self) -> Settings:
            return test_settings

        @provide(scope=Scope.APP)
        def password_hasher(self, settings: Settings) -> PasswordHasher:
            return PasswordHasher(settings.crypto.password_salt)

        @provide(scope=Scope.APP)
        def database(self, settings: Settings) -> DBConnection:
            return DBConnection(
                dsn=settings.db.dsn,
                pool_size=2,
                max_overflow=1,
                pool_timeout=settings.db.pool_timeout,
                pool_recycle=settings.db.pool_recycle,
            )

        @provide(scope=Scope.REQUEST)
        async def uow(
            self, pg: DBConnection
        ) -> AsyncGenerator[DBUnitOfWork, BaseException | None]:
            unit = DBUnitOfWork(pg)
            await unit.begin()
            try:
                error = yield unit
                if error is None:
                    await unit.commit()
                else:
                    await unit.rollback()
            finally:
                await unit.close()

        @provide(scope=Scope.APP)
        def schedule_source(self) -> ScheduleSource:
            return _NullScheduleSource()

        @provide(scope=Scope.APP)
        async def http(
            self, settings: Settings
        ) -> AsyncIterator[HTTPConnection]:
            connection = HTTPConnection(
                max_connections=settings.http.max_connections,
                max_keepalive_connections=(
                    settings.http.max_keepalive_connections
                ),
                keepalive_expiry=settings.http.keepalive_expiry,
                timeout=settings.http.timeout,
                connect_timeout=settings.http.connect_timeout,
                follow_redirects=settings.http.follow_redirects,
            )
            try:
                yield connection
            finally:
                await connection.close()

        @provide(scope=Scope.APP)
        async def es(self, settings: Settings) -> AsyncIterator[ESClient]:
            if settings.es is None:
                raise RuntimeError("Elasticsearch is disabled")
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
        async def redis(
            self, settings: Settings
        ) -> AsyncIterator[RedisClient]:
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

    return TestCoreProvider()


@pytest.fixture
async def dishka_container(integration_settings: Settings, test_dsn: str):
    # Module providers are discovered automatically — new modules need no
    # edit here.
    container = make_async_container(
        core_provider_of(test_settings_of(integration_settings, test_dsn)),
        RateLimitProvider(),
        *get_bootstrapper().boot_providers(),
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def dishka_request(dishka_container):
    async with dishka_container(scope=Scope.REQUEST) as request_container:
        yield request_container


def app_of(container) -> Any:
    """The application, built the way `fastamu.web.app` builds it.

    Routers off the bootstrapper, the framework's exception handlers, dishka
    wired in — so a route test meets the real stack (validation, the envelope,
    the handlers) rather than a hand-assembled imitation.

    Args:
        container: The dishka container to serve requests from.
    Returns:
        (FastAPI): The app, ready to mount on a transport.
    """
    from fastapi import FastAPI

    from fastamu.web.error_handlers import setup_exception_handlers

    app = FastAPI()
    for router in get_bootstrapper().boot_routers():
        app.include_router(router)
    setup_exception_handlers(app)
    setup_dishka(container, app)
    return app


@pytest.fixture
async def api_settings(
    integration_settings: Settings, test_dsn: str, tmp_path: Path
) -> Settings:
    settings = test_settings_of(integration_settings, test_dsn)
    # uploads land in the test's own directory, never in the repo
    return settings.model_copy(
        update={
            "storage": settings.storage.model_copy(
                update={"path": str(tmp_path)}
            )
        }
    )


@pytest.fixture
async def api_container(api_settings: Settings):
    container = make_async_container(
        FastapiProvider(),
        core_provider_of(api_settings),
        RateLimitProvider(),
        *get_bootstrapper().boot_providers(),
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def anonymous(api_container) -> AsyncIterator[AsyncClient]:
    """A client over the live app with no credentials — for public routes, and
    for checking that a guarded one refuses."""
    async with AsyncClient(
        transport=ASGITransport(app=app_of(api_container)),
        base_url="http://testserver",
    ) as client:
        yield client
