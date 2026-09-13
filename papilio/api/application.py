"""Build a web application with its own dependencies."""

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from dishka import Provider, make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware import Middleware
from starlette.types import HTTPExceptionHandler, Lifespan

from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import Settings, get_settings
from papilio.core.logger import logger
from papilio.core.provider import CoreProvider

from .docs import setup_docs
from .middlewares.logging import LoggingMiddleware
from .responses.handlers import setup_exception_handlers


def create_app(
    settings: Settings | None = None,
    *,
    providers: Sequence[Provider] = (),
    routers: Sequence[APIRouter] = (),
    middleware: Sequence[Middleware] | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    exception_handlers: Mapping[int | type[Exception], HTTPExceptionHandler]
    | None = None,
    docs_url: str | None = "/docs",
    **fastapi_options: Any,
) -> FastAPI:
    """Build an app; extra options go directly to FastAPI."""
    config = settings if settings is not None else get_settings()
    bootstrapper = Bootstrapper(config.app.modules)
    discovered = bootstrapper.boot_providers()
    discovered_routers = bootstrapper.boot_routers()
    rate_providers: list[Provider] = []
    if config.rate_limit.enabled:
        from .rate_limit.provider import RateLimitProvider

        rate_providers.append(RateLimitProvider())
    container = make_async_container(
        FastapiProvider(),
        CoreProvider(config),
        *rate_providers,
        *discovered,
        *providers,
    )

    @asynccontextmanager
    async def managed_lifespan(
        app: FastAPI,
    ) -> AsyncGenerator[Mapping[str, Any]]:
        try:
            logger.setup(config.logging)
            if config.es is not None:
                from papilio.infra.es.client import ESClient

                es = await container.get(ESClient)
                await bootstrapper.boot_es_indices(es.client)
            if lifespan is None:
                yield {}
            else:
                async with lifespan(app) as state:
                    yield state or {}
        finally:
            await container.close()

    if middleware is None:
        middleware = (
            Middleware(LoggingMiddleware),
            Middleware(GZipMiddleware, minimum_size=4096),
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        )
        if config.rate_limit.enabled:
            from .rate_limit.middleware import RateLimitMiddleware

            middleware = (
                middleware[0],
                Middleware(RateLimitMiddleware),
                *middleware[1:],
            )
    options = {
        "title": config.fastapi.title,
        "description": config.fastapi.description,
        "version": config.fastapi.version,
        "redoc_url": None,
        **fastapi_options,
    }
    app = FastAPI(
        **options,
        docs_url=None,
        lifespan=managed_lifespan,
        middleware=middleware,
    )
    setup_dishka(container, app)
    setup_exception_handlers(app)
    for key, handler in (exception_handlers or {}).items():
        app.add_exception_handler(key, handler)
    if docs_url is not None and app.openapi_url is not None:
        setup_docs(app, docs_url=docs_url)
    for router in (*discovered_routers, *routers):
        app.include_router(router)
    return app
