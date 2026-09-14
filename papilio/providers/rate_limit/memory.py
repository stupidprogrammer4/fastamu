from dishka import Scope, provide

from papilio.tools.rate_limit.backends.memory import MemoryBackend
from papilio.tools.rate_limit.base import Backend

from .base import RateLimitProvider


class MemoryRateProvider(RateLimitProvider):
    def __init__(self, *, max_size: int = 10000) -> None:
        super().__init__()
        self.max_size = max_size

    @provide(scope=Scope.APP)
    def backend(self) -> Backend:
        return MemoryBackend(max_size=self.max_size)
