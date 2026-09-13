"""The first test: the app your modules make answers."""

from httpx import AsyncClient


async def test_an_unmatched_path_answers_in_the_error_envelope(
    anonymous: AsyncClient,
) -> None:
    response = await anonymous.get("/nothing-is-here")

    assert response.status_code == 404
    assert response.json()["error"]["message_code"] == "route_not_found"
