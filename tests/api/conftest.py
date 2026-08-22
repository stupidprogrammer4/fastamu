"""A live app over the test container.

The app is built the way `src/web/app.py` builds it — routers off the
bootstrapper, the framework's exception handlers, dishka wired in — but on the
test settings, so a route test exercises the real stack (validation, the
envelope, the error handlers) against the test database rather than a mock.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import src.tasks.broker  # noqa: F401
from src.core.bootstrap import get_bootstrapper
from src.core.config import Settings
from src.web.error_handlers import setup_exception_handlers
from tests.conftest import core_provider_of, test_settings_of


def app_of(container) -> FastAPI:
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
    # uploads land in the test's own directory, not in the repo's media/
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
        *get_bootstrapper().boot_providers(),
    )
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def anonymous(api_container) -> AsyncIterator[AsyncClient]:
    """A client with no credentials — for public routes and for checking that
    a guarded one refuses."""
    async with AsyncClient(
        transport=ASGITransport(app=app_of(api_container)),
        base_url="http://testserver",
    ) as client:
        yield client
