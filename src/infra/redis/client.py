from redis.asyncio import Redis


class RedisClient:
    """The async Redis client shared app-wide.

    `Redis` owns its connection pool internally, so one instance is the single
    client to inject everywhere. Use ``.client`` for any operation
    (``await rc.client.get(...)``); ``close()`` is wired to app shutdown.
    """

    def __init__(
        self,
        url: str,
        *,
        max_connections: int,
        socket_timeout: float,
        socket_connect_timeout: float,
        health_check_interval: int,
    ) -> None:
        self.client: Redis = Redis.from_url(
            url,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            decode_responses=True,
        )

    async def close(self) -> None:
        await self.client.aclose()
