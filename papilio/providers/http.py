from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from papilio.core.config import HTTPConfig
from papilio.infra.http.connection import HTTPConnection


class HTTPProvider(Provider):
    def __init__(self, config: HTTPConfig) -> None:
        super().__init__()
        self.config = config

    @provide(scope=Scope.APP)
    async def http(self) -> AsyncIterator[HTTPConnection]:
        connection = HTTPConnection(
            max_connections=self.config.max_connections,
            max_keepalive_connections=self.config.max_keepalive_connections,
            keepalive_expiry=self.config.keepalive_expiry,
            timeout=self.config.timeout,
            connect_timeout=self.config.connect_timeout,
            follow_redirects=self.config.follow_redirects,
        )
        try:
            yield connection
        finally:
            await connection.close()
