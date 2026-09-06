"""The bucket a caller is counted in — the one input an attacker controls.

`client_ip` believes ``X-Forwarded-For`` only from a configured trusted proxy.
Believing it unconditionally would let any caller buy a fresh budget per call;
ignoring it behind a load balancer would count every caller in one bucket.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from fastamu.core.config import get_settings
from fastamu.web.ratelimit import by_ip


def make_request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 1234) if peer else None,
    }
    scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            dishka_container=SimpleNamespace(
                get=AsyncMock(return_value=get_settings())
            )
        )
    )
    return Request(scope)


@pytest.mark.asyncio
async def test_the_peer_is_the_bucket_when_no_proxy_is_trusted() -> None:
    request = make_request("203.0.113.7", forwarded="1.1.1.1")
    assert (await by_ip(request)).removeprefix("ip:") == "203.0.113.7"


@pytest.mark.asyncio
async def test_a_forged_header_from_an_untrusted_peer_is_ignored() -> None:
    get_settings().rate_limit.trusted_proxies.append("10.0.0.1")
    try:
        request = make_request("198.51.100.9", forwarded="1.1.1.1")
        assert (await by_ip(request)).removeprefix("ip:") == "198.51.100.9"
    finally:
        get_settings().rate_limit.trusted_proxies.remove("10.0.0.1")


@pytest.mark.asyncio
async def test_a_trusted_proxy_hands_over_the_original_caller() -> None:
    get_settings().rate_limit.trusted_proxies.append("10.0.0.1")
    try:
        request = make_request("10.0.0.1", forwarded=" 1.1.1.1 , 10.0.0.1 ")
        assert (await by_ip(request)).removeprefix("ip:") == "1.1.1.1"
    finally:
        get_settings().rate_limit.trusted_proxies.remove("10.0.0.1")


@pytest.mark.asyncio
async def test_a_connection_with_no_peer_falls_back_to_unknown() -> None:
    assert await by_ip(make_request(None)) == "ip:unknown"
