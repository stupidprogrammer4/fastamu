from typing import Any

import httpx

from src.infra.http.connection import HTTPConnection

user_agent = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


class BaseGateway:
    """The base for a module's `infra/gateways.py` — one class per third party.

    It owns the three things every gateway otherwise re-implements: the base
    url a path is resolved against, the headers each call carries, and the
    timeout this API in particular deserves. What it deliberately does not own
    is the *meaning* of a response: a subclass reads `httpx.Response` and maps
    it into the module's own domain types, so nobody upstream ends up parsing
    someone else's JSON shape::

        class RatesGateway(BaseGateway):
            __base_url__ = "https://api.example.com/v1"
            default_timeout = 5.0

            async def rate(self, symbol: str) -> Rate:
                resp = await self.get("/rates", params={"symbol": symbol})
                resp.raise_for_status()
                return Rate(**resp.json())

    Take `HTTPConnection` in the constructor and the pool is shared with every
    other gateway; provide the subclass in the module's `providers.py`.
    """

    __base_url__: str = ""
    __method__: str = "GET"

    default_timeout: float | None = None

    def __init__(
        self,
        connection: HTTPConnection,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.connection = connection
        self.headers = headers or {}
        self.timeout = timeout or self.default_timeout

    @property
    def client(self) -> httpx.AsyncClient:
        return self.connection.client

    def url_of(self, path: str) -> str:
        """Resolve a path against `__base_url__`, leaving an absolute URL as
        it is — a paginated API that hands back full `next` links keeps
        working."""
        url = path
        if self.__base_url__ and not path.startswith(("http://", "https://")):
            url = f"{self.__base_url__.rstrip('/')}/{path.lstrip('/')}"
        return url

    def headers_of(
        self,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Per-call headers over the gateway's own, over the default agent."""
        return {"User-Agent": user_agent, **self.headers, **(headers or {})}

    async def request(
        self,
        url: str,
        *,
        method: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        # only override the client's timeout when this gateway asked for one,
        # so the configured default stays the default
        timeout: Any = httpx.USE_CLIENT_DEFAULT
        if self.timeout is not None:
            timeout = self.timeout
        resp = await self.client.request(
            method or self.__method__,
            self.url_of(url),
            headers=self.headers_of(headers),
            params=params,
            json=json,
            data=data,
            timeout=timeout,
        )
        return resp

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.request(
            url, method="GET", headers=headers, params=params
        )

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self.request(
            url,
            method="POST",
            headers=headers,
            params=params,
            json=json,
            data=data,
        )
