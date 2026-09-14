from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from papilio.api.dependencies.rate_limit import (
    by_body_field,
    by_ip,
    rate_limit,
)
from papilio.api.middlewares.rate_limit import RateLimitMiddleware
from papilio.api.responses.handlers import (
    setup_exception_handlers,
)
from papilio.core.config import Settings, get_settings
from papilio.infra.db.uow import UnitOfWork
from papilio.providers.rate_limit.memory import MemoryRateProvider
from papilio.tools.rate_limit.config import RateLimitRule


@pytest.mark.asyncio
@pytest.mark.parametrize("general", [True, False])
async def test_global_cross_path_and_independent_account_limits(general):
    settings = get_settings().model_copy(deep=True)
    settings.rate_limit.enabled = True
    settings.rate_limit.general = RateLimitRule(
        limit=2 if general else 100, window_seconds=60
    )
    settings.rate_limit.rules = {
        "login": RateLimitRule(limit=1, window_seconds=60)
    }

    unit = AsyncMock(spec=UnitOfWork)

    class TestProvider(Provider):
        scope = Scope.APP

        @provide(scope=Scope.REQUEST)
        def uow(self) -> UnitOfWork:
            return unit

        @provide
        def config(self) -> Settings:
            return settings

    container = make_async_container(MemoryRateProvider(), TestProvider())
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    setup_dishka(container, app)
    setup_exception_handlers(app)

    @app.post(
        "/login",
        dependencies=[rate_limit("login", (by_ip, by_body_field("mobile")))],
    )
    async def login():
        return {"ok": True}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            if general:
                assert (await client.get("/one")).status_code == 404
                assert (await client.get("/two")).status_code == 404
                response = await client.get("/three")
            else:
                assert (
                    await client.post("/login", json={"mobile": "a"})
                ).status_code == 200
                # Same IP, different account: the independent IP quota rejects.
                response = await client.post("/login", json={"mobile": "b"})
            assert response.status_code == 429
            assert "retry-after" in response.headers
            assert response.json()["success"] is False
        if not general:
            # The rejected request still charged mobile b's independent bucket.
            async with AsyncClient(
                transport=ASGITransport(app=app, client=("192.0.2.2", 80)),
                base_url="http://test",
            ) as client:
                assert (
                    await client.post("/login", json={"mobile": "b"})
                ).status_code == 429
        unit.rollback.assert_not_awaited()
    finally:
        await container.close()
