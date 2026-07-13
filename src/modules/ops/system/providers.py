from dishka import Provider, Scope, provide

from src.modules.ops.system.app.services import SystemService
from src.modules.ops.system.interfaces import ISystemService


class SystemProvider(Provider):
    # no DB — probes the CoreProvider infra adapters
    system_service = provide(SystemService, provides=ISystemService, scope=Scope.APP)
