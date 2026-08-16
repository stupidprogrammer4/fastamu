"""`BaseGateway` builds the request; these pin the three decisions it makes
before httpx ever sees it — the url, the headers, and whose timeout wins."""

import httpx
import pytest

from src.infra.http.connection import HTTPConnection
from src.infra.http.gateway import BaseGateway, user_agent


class Rates(BaseGateway):
    __base_url__ = "https://api.example.com/v1/"


@pytest.fixture
def connection() -> HTTPConnection:
    return HTTPConnection(
        max_connections=10,
        max_keepalive_connections=5,
        keepalive_expiry=5.0,
        timeout=15.0,
        connect_timeout=5.0,
    )


def test_a_path_resolves_against_the_base_url(connection) -> None:
    gateway = Rates(connection)
    assert gateway.url_of("/rates") == "https://api.example.com/v1/rates"
    assert gateway.url_of("rates") == "https://api.example.com/v1/rates"


def test_an_absolute_url_is_left_alone(connection) -> None:
    # a paginated API hands back full `next` links; re-prefixing them breaks it
    gateway = Rates(connection)
    link = "https://cdn.example.com/page/2"
    assert gateway.url_of(link) == link


def test_a_per_call_header_wins_over_the_gateway_and_the_default(
    connection,
) -> None:
    gateway = Rates(connection, headers={"X-Key": "gateway", "X-Own": "yes"})
    headers = gateway.headers_of({"X-Key": "call"})
    assert headers["X-Key"] == "call"
    assert headers["X-Own"] == "yes"
    assert headers["User-Agent"] == user_agent


async def test_the_client_default_stands_when_no_timeout_is_declared(
    connection,
) -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        seen["url"] = str(request.url)
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(200, json={"ok": True})

    connection.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(15.0, connect=5.0),
    )
    resp = await Rates(connection).get("/rates", params={"symbol": "XAU"})

    assert resp.json() == {"ok": True}
    assert seen["url"] == "https://api.example.com/v1/rates?symbol=XAU"
    assert seen["agent"] == user_agent
    assert seen["timeout"]["connect"] == 5.0
    assert seen["timeout"]["read"] == 15.0


async def test_a_gateway_timeout_overrides_the_client_default(
    connection,
) -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200)

    connection.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(15.0, connect=5.0),
    )

    class Slow(Rates):
        default_timeout = 2.0

    await Slow(connection).get("/rates")
    assert seen["timeout"]["read"] == 2.0
