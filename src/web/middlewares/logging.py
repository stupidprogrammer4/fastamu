from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.core.logger import logger, request_id_ctx


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)

        start = time.perf_counter()
        logger.info("--> %s %s", request.method, request.url.path)

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "<-- %s %s failed after %.2fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            request_id_ctx.reset(token)
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "<-- %s %s %d %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        response.headers[self.header_name] = request_id
        request_id_ctx.reset(token)
        return response
