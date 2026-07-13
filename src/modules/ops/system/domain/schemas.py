from datetime import datetime

from src.common.bases.schemas import BaseOutput


class ComponentHealthOut(BaseOutput):
    healthy: bool
    error: str | None = None


class HealthOut(BaseOutput):
    status: str                                   # "ok" | "degraded"
    components: dict[str, ComponentHealthOut]


class SystemInfoOut(BaseOutput):
    version: str
    python_version: str
    platform: str
    server_time: datetime
