"""The guard, over the live app: a router declaring a scope must refuse an
anonymous caller before any handler runs."""

from httpx import AsyncClient


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
