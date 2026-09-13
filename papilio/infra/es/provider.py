from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from papilio.core.config import ESConfig
from papilio.infra.es.client import ESClient


class ESProvider(Provider):
    def __init__(self, config: ESConfig) -> None:
        super().__init__()
        self.config = config

    @provide(scope=Scope.APP)
    async def es(self) -> AsyncIterator[ESClient]:
        client = ESClient(
            self.config.hosts,
            username=self.config.username,
            password=self.config.password,
            api_key=self.config.api_key,
            verify_certs=self.config.verify_certs,
            ca_certs=self.config.ca_certs,
        )
        try:
            yield client
        finally:
            await client.close()
