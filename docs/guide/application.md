# Application and dependency injection

Each call to `create_app` builds a fresh FastAPI app and Dishka container. Your project owns its ASGI entry point; the framework has no global application module.

## Configure the factory

With your settings and module objects already defined:

```python
from papilio.api.application import create_app

app = create_app(
    settings,
    providers=[ProductsProvider()],
    routers=[health_router],
    title="Shop API",
    root_path="/api",
    docs_url="/reference",
)
```

Extra options go to FastAPI. Explicit routers and providers are added to discovered ones. Avoid registering the same module through both paths.

| Parameter | Behavior |
| --- | --- |
| `settings=None` | Load `config.yml` using `get_settings` |
| `providers` | Add explicit dependencies |
| `routers` | Add explicit routers |
| `middleware=None` | Default logging, GZip, CORS and optional rate limiting |
| `middleware=()` | Remove default middleware; Dishka integration remains |
| `exception_handlers` | Add or replace handlers for exception types/statuses |
| `lifespan` | Your startup and shutdown context |
| `docs_url=None` | Disable Swagger |
| `openapi_url=None` | Disable OpenAPI and Swagger |

## Define a provider

Using the product module from the tutorial:

```python
from dishka import Provider, Scope, provide
from shop.modules.products.app.services import ProductService
from shop.modules.products.infra.repository import ProductRepository
from shop.modules.products.interfaces import IProductService


class ProductProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(ProductRepository)
    service = provide(ProductService, provides=IProductService)
```

Constructor annotations declare actual dependencies. `CoreProvider` supplies base `Settings` and `PasswordHasher`. SQL, Redis, HTTP and Elasticsearch require their corresponding providers.

| Lifetime | Typical objects |
| --- | --- |
| `Scope.APP` | Connection pools, HTTP clients, settings |
| `Scope.REQUEST` | UoW, repositories, application services |

Use `DishkaRoute` with `FromDishka` for route injection; see the [first application](start.md). Use an async generator provider for resources that need cleanup.

## Give an optional tool a managed lifetime

This provider needs the `excel` extra:

```python
from collections.abc import AsyncIterator
from dishka import Provider, Scope, provide
from papilio.infra.excel.writer import ExcelWriter


class ExportProvider(Provider):
    @provide(scope=Scope.APP)
    async def writer(self) -> AsyncIterator[ExcelWriter]:
        writer = ExcelWriter(max_workers=1)
        try:
            yield writer
        finally:
            await writer.close()
```

Pass `ExportProvider()` to the factory or place it in a discovered provider module. The process pool is shared for the app lifetime and closed by the container.

## Custom lifespan

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[dict]:
    yield {"release": "2026.09"}


app = create_app(settings, lifespan=lifespan)
```

The yielded state is available through Starlette request state. Logging setup and configured ES index initialization happen before your lifespan. Your cleanup runs before the container closes. Use a fresh app for each independent test lifecycle.

## Replace middleware deliberately

```python
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from papilio.api.middlewares.logging import LoggingMiddleware

app = create_app(
    settings,
    middleware=[
        Middleware(LoggingMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=["https://shop.example"],
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    ],
)
```

This list replaces defaults. Include GZip or the general rate-limit middleware yourself if required. Default CORS is permissive. Custom exception handlers are async callables accepting request and exception and returning a Response; register them using `exception_handlers={ErrorType: handler}`.

[Factory and bootstrap reference](../reference/application.md)
