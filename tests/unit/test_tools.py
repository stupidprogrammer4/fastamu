import asyncio
import subprocess
import sys
from dataclasses import dataclass

import pytest
import yaml
from dishka import Scope, make_async_container
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from starlette.middleware import Middleware

from papilio.api.application import create_app
from papilio.api.dependencies.auth import bearer, require_access
from papilio.api.middlewares.rate_limit import RateLimitMiddleware
from papilio.core.config import Settings
from papilio.errors.exceptions import UnAuthorizedException
from papilio.providers.rate_limit.memory import MemoryRateProvider
from papilio.scaffolding import project
from papilio.scaffolding.options import Infrastructure
from papilio.security.tokens import create_access_token, create_refresh_token
from papilio.tools.auth import JWTAuth
from papilio.tools.rate_limit.backends.memory import MemoryBackend
from papilio.tools.rate_limit.config import RateLimitRule
from papilio.tools.rate_limit.limiter import RateLimiter


def settings():
    config = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop")["config.yml"])
    )
    config.app.modules = []
    return config


async def test_plain_app_has_no_auth_or_automatic_limits():
    config = settings()
    assert config.jwt is config.crypto is config.csrf is None
    config.rate_limit.enabled = True
    app = create_app(config, docs_url=None)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(3):
                assert (await client.get("/absent")).status_code == 404
    assert all(m.cls is not RateLimitMiddleware for m in app.user_middleware)


async def test_custom_authenticator_and_identity_type_without_framework_jwt():
    @dataclass
    class User:
        name: str
        scopes: frozenset[str]

    async def authenticate(token):
        return User(token, frozenset({"read"}))

    current = bearer(authenticate)
    app = create_app(settings(), docs_url=None)

    @app.get("/me")
    async def me(user=Depends(require_access(current, "read"))):
        return {"name": user.name}

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/me")).status_code == 401
            result = await client.get(
                "/me", headers={"Authorization": "Bearer custom"}
            )
            assert result.json() == {"name": "custom"}


async def test_ready_jwt_auth_validates_access_tokens():
    auth = JWTAuth("a sufficiently long test secret key")
    token = create_access_token(
        "42",
        auth.secret_key,
        expires_minutes=5,
        extra_claims={"scopes": ["read"]},
    )
    user = await auth.authenticate(token)
    assert user.subject == "42" and user.scopes == {"read"}
    refresh = create_refresh_token("42", auth.secret_key, expires_minutes=5)
    with pytest.raises(UnAuthorizedException):
        await auth.authenticate(refresh)


async def test_memory_backend_is_atomic_and_instances_are_isolated():
    rule = RateLimitRule(limit=10, window_seconds=60)
    backend = MemoryBackend()
    results = await asyncio.gather(
        *(backend.limit("same", rule) for _ in range(100))
    )
    assert sum(not r.limited for r in results) == 10
    assert not (await MemoryBackend().limit("same", rule)).limited
    assert not (await backend.limit("different", rule)).limited


async def test_memory_provider_is_shared_only_within_its_container():
    first = make_async_container(MemoryRateProvider())
    second = make_async_container(MemoryRateProvider())
    try:
        limiter = await first.get(RateLimiter)
        assert await first.get(RateLimiter) is limiter
        assert await second.get(RateLimiter) is not limiter
        async with first(scope=Scope.REQUEST) as scope:
            assert await scope.get(RateLimiter) is limiter
    finally:
        await first.close()
        await second.close()


async def test_memory_budget_recovers_after_window_expiry(monkeypatch):
    from throttled import utils

    now = [60000]
    monkeypatch.setattr(utils, "now_ms", lambda: now[0])
    monkeypatch.setattr(utils, "now_sec", lambda: now[0] // 1000)
    backend = MemoryBackend()
    rule = RateLimitRule(limit=1, window_seconds=60)
    assert not (await backend.limit("key", rule)).limited
    assert (await backend.limit("key", rule)).limited
    now[0] = 120000
    assert (await backend.limit("key", rule)).limited
    now[0] = 121000
    assert not (await backend.limit("key", rule)).limited
    now[0] += 120001
    assert not (await backend.limit("key", rule)).limited


async def test_explicit_memory_middleware_limits_without_redis():
    config = settings()
    config.rate_limit.enabled = True
    config.rate_limit.general = RateLimitRule(limit=1, window_seconds=60)
    app = create_app(
        config,
        providers=[MemoryRateProvider()],
        middleware=[Middleware(RateLimitMiddleware)],
        docs_url=None,
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/one")).status_code == 404
            assert (await client.get("/two")).status_code == 429


def test_memory_imports_without_optional_backends(
    tmp_path,
):
    script = """
import asyncio
import importlib.abc
import sys
class Missing(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'redis', 'jwt', 'bcrypt', 'cryptography', 'fastapi_csrf_protect',
            'sqlalchemy', 'sqlmodel', 'elasticsearch',
        }:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, Missing())
from papilio.api.application import create_app
from papilio.api.dependencies.auth import bearer
from papilio.tools.checks import Checks
from papilio.tools.ids import IDEncryption
from papilio.providers.rate_limit.memory import MemoryRateProvider
from papilio.tools.rate_limit.limiter import RateLimiter
from papilio.tools.rate_limit.config import RateLimitRule
from dishka import make_async_container
async def main():
    container = make_async_container(MemoryRateProvider())
    try:
        limiter = await container.get(RateLimiter)
        rule = RateLimitRule(limit=2, window_seconds=60)
        assert await limiter.check('key', rule)
    finally:
        await container.close()
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_scaffold_backend_choice_is_explicit_in_generated_wiring():
    memory = project.files("shop", "Shop", infra=[Infrastructure.RATE_LIMIT])
    assert "MemoryRateProvider" in memory["shop/main.py"]
    assert "RedisProvider" not in memory["shop/main.py"]
    assert "middleware=middleware" in memory["shop/main.py"]
    redis = project.files(
        "shop", "Shop", infra=[Infrastructure.RATE_LIMIT, Infrastructure.REDIS]
    )
    assert "RedisRateProvider" in redis["shop/main.py"]
    assert "RedisProvider" in redis["shop/main.py"]
