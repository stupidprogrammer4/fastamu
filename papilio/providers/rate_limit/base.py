from dishka import Provider, Scope, provide

from papilio.tools.rate_limit.base import Backend
from papilio.tools.rate_limit.limiter import RateLimiter


class RateLimitProvider(Provider):
    @provide(scope=Scope.APP)
    def limiter(self, backend: Backend) -> RateLimiter:
        return RateLimiter(backend)
