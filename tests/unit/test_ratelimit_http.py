from typing import cast
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from throttled.asyncio.store import MemoryStore, RedisStore

from fastamu.core.config import RateLimitRule, Settings, get_settings
from fastamu.infra.db.uow import DBUnitOfWork, rollback_transaction
from fastamu.web.error_handlers import setup_exception_handlers
from fastamu.web.ratelimit import (
    RateLimitMiddleware,
    RateLimitProvider,
    by_body_field,
    by_ip,
    rate_limit,
)


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

    unit = AsyncMock(spec=DBUnitOfWork)

    class TestProvider(Provider):
        rollback = provide(
            staticmethod(rollback_transaction),
            scope=Scope.REQUEST,
            cache=False,
        )

        scope = Scope.APP

        @provide(scope=Scope.REQUEST)
        def uow(self) -> DBUnitOfWork:
            return unit

        @provide
        def config(self) -> Settings:
            return settings

        @provide(override=True)
        def store(self) -> RedisStore:
            return cast(RedisStore, MemoryStore())

    container = make_async_container(RateLimitProvider(), TestProvider())
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
        assert unit.rollback.await_count == (3 if general else 2)
    finally:
        await container.close()
