import platform
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from src.common.utils import date_utils
from src.core.config import Settings
from src.infra.es.client import ESClient
from src.infra.postgres.connection import PGConnection
from src.infra.redis.client import RedisClient
from src.modules.ops.system.domain.schemas import ComponentHealthOut, HealthOut, SystemInfoOut


class SystemService:
    """Liveness/health of the backing services + basic runtime info. No DB model
    of its own — it just probes the shared infra adapters."""

    def __init__(
        self,
        settings: Settings,
        pg: PGConnection,
        redis: RedisClient,
        es: ESClient,
    ) -> None:
        self.settings = settings
        self.pg = pg
        self.redis = redis
        self.es = es

    async def health(self) -> HealthOut:
        """Probe each backing service and report overall health.

        Returns:
            (HealthOut): Per-component health and an "ok"/"degraded" summary.
        """
        components = {
            "postgres": await self._check(self._ping_postgres),
            "redis": await self._check(self._ping_redis),
            "elasticsearch": await self._check(self._ping_es),
        }
        status = "ok" if all(component.healthy for component in components.values()) else "degraded"
        return HealthOut(status=status, components=components)

    async def info(self) -> SystemInfoOut:
        """Get basic runtime info (app version, python/platform, server time).

        Returns:
            (SystemInfoOut): The runtime info.
        """
        return SystemInfoOut(
            version=self.settings.fastapi.version,
            python_version=platform.python_version(),
            platform=platform.platform(),
            server_time=date_utils.utc_now(),
        )

    async def _check(self, probe: Callable[[], Awaitable[None]]) -> ComponentHealthOut:
        """Run a probe, capturing any failure as an unhealthy component."""
        result = ComponentHealthOut(healthy=True)
        try:
            await probe()
        except Exception as exc:
            result = ComponentHealthOut(healthy=False, error=str(exc))
        return result

    async def _ping_postgres(self) -> None:
        async with self.pg.session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def _ping_redis(self) -> None:
        await self.redis.client.ping() # type: ignore

    async def _ping_es(self) -> None:
        await self.es.client.ping()
