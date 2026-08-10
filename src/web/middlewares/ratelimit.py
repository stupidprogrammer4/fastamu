from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from src.common.enums import MediaType
from src.core.config import get_settings
from src.infra.ratelimit.keys import client_ip
from src.infra.ratelimit.limiter import get_limiter

from ..response import APIResponse

NAMESPACE = "rl:general"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """The blanket budget: `rate_limit.general` per client, on every route.

    It floors the whole surface, including routes nobody remembered to guard;
    a named `rate_limit(...)` rule then narrows a specific one on top.

    The refusal is built here rather than raised, because a middleware sits
    outside the exception handlers — so it is assembled through `APIResponse`
    to leave in exactly the envelope those handlers would have produced.
    Successful answers carry the `RateLimit-*` headers too, so a client can
    pace itself before it is refused."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.cfg = get_settings().rate_limit
        self.limiter = get_limiter()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.cfg.enabled:
            return await call_next(request)

        key = f"{NAMESPACE}:{client_ip(request)}"
        verdict = await self.limiter.hit(key, self.cfg.general)
        if not verdict.allowed:
            refused = self.limiter.refuse(verdict)
            response_model = APIResponse.from_external_error(refused)
            return JSONResponse(
                content=response_model.model_dump(exclude_defaults=True),
                status_code=refused.status_code,
                headers={
                    **verdict.headers(),
                    "Retry-After": str(verdict.retry_after),
                },
                media_type=MediaType.JSON,
            )

        response = await call_next(request)
        for name, value in verdict.headers().items():
            response.headers.setdefault(name, value)
        return response
