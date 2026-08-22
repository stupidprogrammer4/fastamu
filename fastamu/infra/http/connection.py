import httpx


class HTTPConnection:
    """The outbound HTTP client pool, shared app-wide.

    One `AsyncClient` for the whole process, injected wherever a gateway needs
    it: the point is the connection pool behind it. A client built per call
    re-runs DNS and the TLS handshake every time and leaks sockets on the way
    out, which is why a third-party API that was fine in development starts
    timing out under load.

    Both timeouts are set, not just the total: `connect_timeout` bounds how
    long a dead host can hold a task before it is even talking, which is the
    failure a total timeout notices far too late.
    """

    def __init__(
        self,
        *,
        max_connections: int,
        max_keepalive_connections: int,
        keepalive_expiry: float,
        timeout: float,
        connect_timeout: float,
        follow_redirects: bool = True,
    ) -> None:
        self.client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
                keepalive_expiry=keepalive_expiry,
            ),
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            follow_redirects=follow_redirects,
        )

    async def close(self) -> None:
        await self.client.aclose()
