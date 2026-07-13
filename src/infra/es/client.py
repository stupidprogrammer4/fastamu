from typing import Any

from elasticsearch import AsyncElasticsearch


class ESClient:
    """The async Elasticsearch client shared app-wide.

    Use ``.client`` for raw calls, or pass it to an `ESRepository` /
    `AsyncDocument` via ``using=``. ``close()`` is wired to app shutdown.
    """

    def __init__(
        self,
        hosts: list[str],
        *,
        username: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
    ) -> None:
        options: dict[str, Any] = {"hosts": hosts, "verify_certs": verify_certs}
        if username and password:
            options["basic_auth"] = (username, password)
        if api_key:
            options["api_key"] = api_key
        if ca_certs:
            options["ca_certs"] = ca_certs

        self.client = AsyncElasticsearch(**options)

    async def close(self) -> None:
        await self.client.close()
