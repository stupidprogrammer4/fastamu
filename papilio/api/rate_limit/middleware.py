"""Application-wide HTTP rate limiting."""

from math import ceil

from fastapi import Request
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response
from throttled.asyncio import Throttled
from throttled.asyncio.rate_limiter import RateLimitState

from papilio.api.rate_limit.dependencies import _check, by_ip
from papilio.core.config import Settings
from papilio.errors.base import APPException
from papilio.errors.exceptions import TooManyRequestsException


def _headers(state: RateLimitState) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(state.limit),
        "RateLimit-Remaining": str(state.remaining),
        "RateLimit-Reset": str(ceil(state.reset_after)),
    }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """One IP budget across all paths, including unmatched routes."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        container = request.app.state.dishka_container
        settings = await container.get(Settings)
        if not settings.rate_limit.enabled:
            response = await call_next(request)
        else:
            limiter = await container.get(Throttled)
            # Keep the existing global counter namespace.
            key = (await by_ip(request)).removeprefix("ip:")
            try:
                state = await _check(
                    limiter, f"rl:general:{key}", settings.rate_limit.general
                )
            except TooManyRequestsException as exc:
                handler = request.app.exception_handlers[APPException]
                response = await handler(request, exc)
                response.headers["RateLimit-Reset"] = str(
                    settings.rate_limit.general.window_seconds
                )
            else:
                response = await call_next(request)
                if state is not None:
                    for name, value in _headers(state).items():
                        response.headers.setdefault(name, value)
        return response
