import pytest
from httpx import ASGITransport, AsyncClient

from papilio.core.config import get_settings


@pytest.fixture
async def anonymous():
    from <<PKG>>.main import build_app

    settings = get_settings().model_copy(deep=True)
    settings.rate_limit.enabled = False
    if settings.db is not None:
        settings.db.dsn = settings.db.test_dsn
    app = build_app(settings)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
