from contextlib import asynccontextmanager

from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka, FastapiProvider
from fastapi import Depends, FastAPI, dependencies
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.core.bootstrap import get_bootstrapper
from src.core.config import get_settings
from src.core.provider import CoreProvider
from src.infra.es.client import ESClient

from .error_handlers import setup_exception_handlers
from .docs import setup_docs
from .middlewares.logging import LoggingMiddleware

# get settings
settings = get_settings()

# bootstrap
bootstrapper = get_bootstrapper()

import src.tasks.broker  # noqa: E402, F401

providers = bootstrapper.boot_providers()
routers = bootstrapper.boot_routers()
bootstrapper.boot_sqlmodels()

container = make_async_container(
    FastapiProvider(),
    CoreProvider(),
    *providers
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    async with container() as request_container:
        es_client = await request_container.get(ESClient)
        await bootstrapper.boot_es_indices(es_client.client)
    yield
    await container.close()

app = FastAPI(
    title=settings.fastapi.title,
    description=settings.fastapi.description,
    version=settings.fastapi.version,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=4096)
app.add_middleware(LoggingMiddleware)

setup_dishka(container, app)
setup_exception_handlers(app)
setup_docs(app)

for router in routers:
    app.include_router(router)
