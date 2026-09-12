from contextlib import asynccontextmanager

from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.config import get_settings
from fastamu.core.provider import CoreProvider
from fastamu.infra.es.client import ESClient
from fastamu.tasks.lifespan import task_lifespan

from .docs import setup_docs
from .error_handlers import setup_exception_handlers
from .middlewares.logging import LoggingMiddleware
from .ratelimit import RateLimitMiddleware, RateLimitProvider

# get settings
settings = get_settings()

# bootstrap
bootstrapper = get_bootstrapper()


providers = bootstrapper.boot_providers()
routers = bootstrapper.boot_routers()
bootstrapper.boot_sqlmodels()

container = make_async_container(
    FastapiProvider(), CoreProvider(), RateLimitProvider(), *providers
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        async with task_lifespan(container):
            if settings.es is not None:
                async with container() as request_container:
                    es_client = await request_container.get(ESClient)
                    await bootstrapper.boot_es_indices(es_client.client)
            yield
    finally:
        await container.close()


app = FastAPI(
    title=settings.fastapi.title,
    description=settings.fastapi.description,
    version=settings.fastapi.version,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=4096)
# added before LoggingMiddleware, so logging stays the outermost layer and a
# refused call is still logged and still answers with its request id
app.add_middleware(RateLimitMiddleware)
app.add_middleware(LoggingMiddleware)

setup_dishka(container, app)
setup_exception_handlers(app)
setup_docs(app)

for router in routers:
    app.include_router(router)
