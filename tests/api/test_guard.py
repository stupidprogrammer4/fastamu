"""An explicit guard rejects anonymous requests before the route handler."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from papilio.api.dependencies.auth import Scoped, bearer, require_access
from papilio.api.responses.handlers import setup_exception_handlers


@pytest.fixture
async def anonymous():
    async def authenticate(token: str) -> Scoped:
        raise AssertionError("Anonymous requests must not authenticate")

    app = FastAPI()
    setup_exception_handlers(app)
    guard = require_access(bearer(authenticate), "jobs:read")

    @app.get("/jobs", dependencies=[Depends(guard)])
    async def jobs():
        raise AssertionError("Anonymous requests must not reach the handler")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_a_guarded_route_refuses_an_anonymous_caller(
    anonymous: AsyncClient,
) -> None:
    response = await anonymous.get("/jobs")

    assert response.status_code == 401
    assert response.json()["success"] is False


async def test_the_refusal_leaves_in_the_standard_envelope(
    anonymous: AsyncClient,
) -> None:
    response = await anonymous.get("/jobs")

    body = response.json()
    assert body["error"]["message_code"] == "missing_token"
    assert "data" not in body


async def test_an_unmatched_path_is_a_route_not_found(
    anonymous: AsyncClient,
) -> None:
    response = await anonymous.get("/nothing-is-here")

    assert response.status_code == 404
    assert response.json()["error"]["message_code"] == "route_not_found"
