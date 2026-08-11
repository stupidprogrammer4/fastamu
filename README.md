# Fastamu

**A convention-driven, modular-monolith framework for Python backends.**

FastAPI is not a framework. It is an excellent *router* with request validation
attached — it has no opinion about how you wire dependencies, where your business
logic lives, how you talk to a database, how you run background work, or what
your responses look like. Every team that adopts it ends up rebuilding the same
missing 80% by hand.

Fastamu is that missing 80%, assembled once. It takes a set of best-in-class,
independently-maintained tools — FastAPI, dishka, taskiq, SQLModel,
Elasticsearch, Redis — and fuses them into a single coherent framework where
**everything wires itself by convention**. Modules are auto-discovered. DI,
routing, background tasks, migrations and tests all find your code without you
registering it anywhere. There is no `app_registry.py`, no aggregator module, no
`include_router` list to maintain.

Adding a feature is one command and one folder.

```bash
python -m src.manager module catalog.product --cqrs
# ✓ created CQRS module 'catalog.products' at src/modules/catalog/products
```

That's it. The router is live, the service is injectable, the table is in the next
migration, the ES index is created on boot, and the projection job is registered
on the broker — because the bootstrapper found them.

---

## Table of contents

- [The stack: what each tool does](#the-stack-what-each-tool-does)
- [Quickstart](#quickstart)
- [Project layout](#project-layout)
- [The core idea: a module](#the-core-idea-a-module)
- [The discovery contract](#the-discovery-contract)
- [Scaffolding a module](#scaffolding-a-module)
- [Tutorial: building a feature end to end](#tutorial-building-a-feature-end-to-end)
- [Dependency injection](#dependency-injection)
- [The data layer](#the-data-layer)
- [Responses and errors](#responses-and-errors)
- [Authentication and scopes](#authentication-and-scopes)
- [Rate limiting](#rate-limiting)
- [Background tasks and scheduling](#background-tasks-and-scheduling)
- [CQRS: the Elasticsearch read side](#cqrs-the-elasticsearch-read-side)
- [Other infrastructure](#other-infrastructure)
- [Migrations](#migrations)
- [Testing](#testing)
- [Configuration reference](#configuration-reference)
- [Reference modules](#reference-modules)
- [House rules](#house-rules)

---

## The stack: what each tool does

Fastamu is deliberately not a from-scratch framework. Each concern is delegated
to a mature library; Fastamu's value is the **integration layer** that makes them
behave as one thing.

| Concern | Tool | What Fastamu adds on top |
|---|---|---|
| HTTP, validation, OpenAPI | **FastAPI** | Auto-included routers, a uniform response envelope, typed error handlers, offline (CDN-free) Swagger UI |
| Dependency injection | **dishka** | A `CoreProvider` with the whole infra layer pre-wired; per-module providers discovered and merged automatically; `APP`/`REQUEST` scopes shared identically by the web app *and* the task worker |
| Background jobs & cron | **taskiq** (Redis streams) | A broker that boots the same DI container as the web app, per-module task auto-registration, per-projection queues, retry + logging middleware |
| Write side / ORM | **SQLModel** + **SQLAlchemy 2.0** (async) | Generic `PGRepository` hierarchy built on `RETURNING`, patch-semantics writes, statement-agnostic pagination, bulk upsert/update helpers, a `UnitOfWork` bound to the request |
| Read side / search | **Elasticsearch DSL** (async) | `ESRepository`, index auto-creation on boot, and `@project` / `@batch_project` / `@unproject` decorators that keep the read model in sync with every write |
| Migrations | **Alembic** | Metadata pulled straight from the bootstrapper, so `--autogenerate` sees every module without imports |
| Cache / broker | **Redis** | Pooled async client, injectable |
| Logging | **Rich / orjson** | One switch between Rich console output and ECS-shaped JSON lines, a request id on every record, and uvicorn/gunicorn/taskiq adopted into the same handler |
| Spreadsheets | **openpyxl / xlsxwriter** | Async reader/writer that offloads to a `ProcessPool` so a large workbook never blocks the event loop |
| Validation vocabulary | **pydantic v2** | A shared library of semantic type aliases (`RialType`, `SlugType`, `MobileType`, …) |
| Scaffolding | **typer** | A CLI that generates a complete, correctly-layered module |
| Tests | **pytest** + pytest-asyncio | Async-by-default, real-database fixtures, and a DI container that discovers modules exactly like production does |

---

## Quickstart

**Runtime requirements:** Python **3.13+**, **PostgreSQL**, **Redis**.
Elasticsearch is only needed if you use the CQRS read side.

```bash
# 1) Environment
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2) Config — config.yml is gitignored; it holds your secrets
cp config.yml.sample config.yml
#    fill in: postgresql.dsn, postgresql.test_dsn, redis.url,
#             taskiq.redis_url, jwt.secret_key, crypto.encryption_key

# 3) Schema
alembic upgrade head

# 4) API
fastapi dev src/web/app.py          # or: uvicorn src.web.app:app --reload

# 5) Worker + scheduler (separate processes)
taskiq worker    src.tasks.broker:broker
taskiq scheduler src.tasks.scheduler:scheduler
```

Swagger UI is served at **`/docs`**, self-hosted from `/static/swagger` — no CDN,
so it works on an air-gapped box.

> **`config.yml` is resolved relative to the current working directory.** Always
> launch from the repo root. There is no `.env` / environment-variable override
> layer: the YAML file is the single source of configuration.

---

## Project layout

```
src/
├── common/          # Shared foundations — depend on nothing else in the app
│   ├── bases/       # BaseService, BaseDTO, BaseOutput, BaseMeta, PagedType,
│   │                # BatchResultType, AbstractESProjection, EventHandler,
│   │                # IDEncryption
│   ├── errors/      # APPException hierarchy + the *ErrorOut wire schemas
│   ├── utils/       # date / jwt / crypto / string / persian / currency
│   ├── types.py     # validation aliases (IdType, SlugType, RialType, …)
│   ├── enums.py  constants.py
│
├── core/            # The framework's heart
│   ├── bootstrap.py # Auto-discovery: modules, routers, providers, models,
│   │                # ES documents, tasks
│   ├── config.py    # Settings loaded from config.yml (pydantic)
│   ├── provider.py  # CoreProvider — Settings / PG / UoW / Redis / ES / scheduler
│   ├── logger.py    # console or ECS-JSON logging, request-id ContextVar
│   └── resources.py # Global message codes
│
├── infra/           # Adapters to the outside world
│   ├── postgres/    # model bases, repository bases, connection, uow,
│   │                # column types
│   ├── es/          # client, repository, analyzers
│   ├── redis/       # pooled async client
│   ├── ratelimit/   # sliding-window limiter, bucket keys, the route guard
│   └── excel/       # ProcessPool-backed reader / writer
│
├── tasks/           # taskiq
│   ├── broker.py    # The broker (boots its own DI container)
│   ├── scheduler.py # TaskiqScheduler (label + Redis schedule sources)
│   ├── projection.py# @project / @batch_project / @unproject
│   └── middlewares/ # logging
│
├── web/             # The HTTP layer
│   ├── app.py       # App construction: bootstrap → container → routers
│   ├── dependencies.py # Auth (generic placeholder) + decode_path_id
│   ├── response.py  # APIResponse envelope
│   ├── error_handlers.py
│   ├── docs.py      # Offline Swagger UI
│   └── middlewares/ # request-id + access logging, app-wide rate limit
│
├── manager.py       # The scaffolding CLI
└── modules/         # Your features live here — grouped or not
    └── ops/{jobs,storage,system}/   # Reference modules — see below
```

**Dependency direction is strictly inward.** `routers` / `tasks` / `app` / `infra`
all depend on `domain`; `domain` knows nothing about HTTP, SQL or Elasticsearch.

---

## The core idea: a module

A feature is a **module**: `src/modules/<name>/`. Modules may be filed under a
**group** — `src/modules/<group>/<name>/` — but a group is nothing more than a
namespace folder, and it is entirely optional. `modules/pricing/` and
`modules/catalog/products/` are both perfectly ordinary modules; group things
when grouping earns its keep, not because the layout demands it.

```
modules/[<group>/]<name>/
├── domain/         # The inward core — no I/O
│   ├── models.py       # SQLModel tables            (write model)
│   ├── dtos.py         # BaseDTO                    (validated input)
│   ├── schemas.py      # BaseOutput                 (wire output)
│   ├── enums.py
│   └── documents.py    # AsyncDocument  (CQRS only) (ES read model)
├── app/            # Business logic
│   ├── services.py
│   ├── helpers.py
│   ├── commands.py     # (CQRS only) writes that trigger projections
│   └── queries.py      # (CQRS only) reads that hit Elasticsearch
├── infra/          # This module's adapters
│   ├── repository.py
│   ├── projections.py  # (CQRS only)
│   ├── gateways.py     # (--http)  outbound HTTP clients
│   └── exporters.py    # (--excel) file/spreadsheet exporters
├── routers/        # One file per concern (admin.py, public.py, …)
├── tasks/          # One file per group of taskiq tasks
├── interfaces.py   # I*Service Protocols — the module's public contract
├── providers.py    # The module's dishka Provider
└── resources.py    # Module-scoped message codes (add by hand when you need them)
```

Everything except `domain/` or `app/` is optional — a module with no table, no
router and no tasks is perfectly legal (`ops/system` is exactly that).

### Context modules: when the module owns logic, not rows

Some modules own no data at all. A pricing engine reads a handful of fields —
today's metal rate, a margin, a tax band — and turns them into a number. It has
no table to write, nothing to project into Elasticsearch, and no CRUD surface;
what it has is **rules**. Modelling it as a resource with a `*Model` and a
repository would be inventing a row that never existed.

Such a module replaces its write model with a **context**: a frozen dataclass in
`domain/context.py` holding exactly the facts the logic runs on.

```
modules/pricing/
├── domain/
│   ├── context.py   # PricingContext — the facts, frozen
│   ├── dtos.py      # PricingInput
│   ├── schemas.py   # PricingOut
│   └── enums.py
├── app/services.py  # the engine
├── infra/readers.py # PricingReader — pulls only the columns it needs
├── routers/  interfaces.py  providers.py
```

The reader extends `PGReader` — a repository base with no model bound to it,
just the session — and returns a context instead of rows. The service splits in
two: `run()` sits at the edge and does the reading, `calculate()` stays pure.

```python
class PricingService:
    def __init__(self, reader: PricingReader) -> None:
        self.reader = reader

    async def run(self, data: PricingInput) -> PricingOut:
        context = await self.reader.read()
        return self.calculate(context, data)

    def calculate(self, context: PricingContext, data: PricingInput) -> PricingOut:
        ...
```

That seam is the whole point: `calculate` is a pure function of a context and an
input, so the rules that actually matter are unit-testable without a database,
a container or a running app. Scaffold one with `--context`.

**Modules never import each other directly.** Cross-module collaboration goes
through an `I*Service` `Protocol` declared in `interfaces.py` and injected by
dishka. That is what keeps a modular monolith from quietly becoming a big ball of
mud — and what makes any module extractable into its own service later.

---

## The discovery contract

This is the single most important section. There is **no registration anywhere**;
the bootstrapper ([src/core/bootstrap.py](src/core/bootstrap.py)) finds your code
by walking `src.modules` and looking for exactly five paths.

A package under `src/modules/` is recognised as a **module** if — and only if — it
contains a `domain/` or an `app/` sub-package. Anything else is treated as a
**group** and scanned one level deeper. That's the whole rule — and it is why a
group is optional: `modules/pricing/` is found by the same rule that finds
`modules/catalog/products/`.

| What | Where the bootstrapper looks | What it collects |
|---|---|---|
| **Routers** | `<module>/routers/*.py` | Every module-level `APIRouter` instance (deduped), then `app.include_router(...)` |
| **Providers** | `<module>/providers.py` | Every `dishka.Provider` subclass, instantiated and merged into the container |
| **Tables** | `<module>/domain/models.py` | Imported so `SQLModel` tables register on the shared metadata (this is what Alembic autogenerate sees) |
| **ES documents** | `<module>/domain/documents.py` | Every `AsyncDocument` subclass; its index is created on app startup if missing |
| **Tasks** | `<module>/tasks/*.py` | Imported so `@broker.task` registers each task on the broker |

Consequences worth internalising:

- **`routers/` and `tasks/` are packages whose `__init__.py` stays empty.** The
  bootstrapper imports each *file* inside them. Re-exporting from `__init__.py`
  is not just unnecessary, it is against the convention.
- **`providers.py` and `domain/models.py` are single files**, not packages.
- **Every one of these is optional.** A module with no `tasks/` folder simply has
  no tasks. A missing file is skipped silently; a file that *exists but fails to
  import* raises loudly (for routers), so typos don't silently unmount your API.
- **The bootstrapper does not invent prefixes or tags.** Your router declares its
  own `prefix=` and `tags=`. The scaffolder writes the pluralised convention for
  you.
- **The same bootstrapper runs in four places** — the web app, the taskiq broker,
  Alembic's `env.py`, and the pytest fixtures — so all four see an identical view
  of your modules. Add a module, and migrations, DI, the worker and the test
  container all pick it up with zero edits.

---

## Scaffolding a module

Run from the repo root. Pass the name as `<singular-name>`, or as
`<group>.<singular-name>` to file it under a group; the CLI pluralises the
folder, the router prefix, the tags and the table name, while class names stay
singular.

```bash
python -m src.manager module product                   # CRUD, no group
python -m src.manager module catalog.product           # CRUD, filed under catalog/
python -m src.manager module catalog.product --cqrs    # + ES read model, projection, commands/queries
python -m src.manager module pricing --context         # pure logic: context + reader, no models
python -m src.manager module catalog.product --tasks   # + tasks/
python -m src.manager module catalog.product --http    # + infra/gateways.py
python -m src.manager module catalog.product --excel   # + infra/exporters.py
```

Flags compose freely (`--cqrs --tasks --excel`); `--context` is the one exclusion
— a module with no table cannot have a read side to project into, so it rejects
`--cqrs`. The console script `fastamu` is also installed by `pip install -e .`,
so `fastamu module catalog.product` works too.

What `catalog.product` produces:

| | |
|---|---|
| Folder | `src/modules/catalog/products/` |
| Classes | `ProductModel`, `ProductCreate`, `ProductUpdate`, `ProductOut`, `ProductRepository`, `ProductService`, `IProductService`, `ProductProvider` |
| Table | `tbl_products` |
| Router | `APIRouter(prefix="/products", tags=["products"])` |

What `pricing --context` produces:

| | |
|---|---|
| Folder | `src/modules/pricing/` — **not** pluralised; an engine is not a collection |
| Classes | `PricingContext`, `PricingInput`, `PricingOut`, `PricingReader`, `PricingService`, `IPricingService`, `PricingProvider` |
| Table | none — no `domain/models.py`, no `domain/documents.py` |
| Router | `APIRouter(prefix="/pricing", tags=["pricing"])` |

The group folder is created on first use. Generated files are correctly layered
and cross-imported, with method bodies left as `raise NotImplementedError` — the
wiring is done, the logic is yours.

---

## Tutorial: building a feature end to end

Let's build `catalog.brand` as a plain CRUD module. Start with the scaffold:

```bash
python -m src.manager module catalog.brand
```

### 1. The table — `domain/models.py`

Inherit `BaseIDTimestampModel` and you get `id`, `created_at`, `updated_at` and an
auto-derived table name (`tbl_brands`). Columns are declared with the **field
factories** from [src/infra/postgres/types.py](src/infra/postgres/types.py), which
default to `NOT NULL` — nullability is opt-in, not opt-out.

```python
from src.infra.postgres.models.base import BaseIDTimestampModel
from src.infra.postgres.types import BoolField, CharField


class BrandModel(BaseIDTimestampModel, table=True):
    name: str = CharField(35, index=True)
    slug: str = CharField(55, unique=True)
    is_active: bool = BoolField(default=True)
```

Bases: `BaseModel` (bare), `BaseIDModel`, `BaseTimestampModel`,
`BaseIDTimestampModel`.

Field factories: `IDField`, `SmallIntField`, `IntField`, `BigIntField`, `BoolField`,
`FloatField`, `NumericField`, `CharField`, `TextField`, `DateField`,
`TimestampField` (timezone-aware), `JSONBField`, `ArrayField` (optional GIN index),
`EnumField` (native PG enum), `ComputedField` (generated column), `ForeignKeyField`.

> **Table naming gotcha.** `__tablename__` is derived as
> `tbl_ + pluralize(ClassName.removesuffix("Model").lower())`. It does **not**
> snake-case, so `ProductTagModel` becomes `tbl_producttags`. Multi-word models and
> irregular plurals should set `__tablename__` explicitly — as `ops/storage` does
> (`tbl_media`).

### 2. Validated input — `domain/dtos.py`

DTOs are **plain pydantic**, never SQLModel: input validation must not depend on
the ORM. Draw the field types from [src/common/types.py](src/common/types.py) so
validation rules stay consistent across the codebase.

```python
from src.common.bases.dtos import BaseDTO
from src.common.types import SlugType, StrType


class BrandCreate(BaseDTO):
    name: StrType
    slug: SlugType


class BrandUpdate(BaseDTO):
    name: StrType | None = None
    is_active: bool | None = None
```

`BaseDTO.to_row()` turns a DTO into a column dict. It defaults to
`exclude_unset=True`, which is what gives `BrandUpdate` correct **PATCH
semantics** — a field the client never sent is never written. Pass
`exclude_unset=False` on create to let defaults materialise.

### 3. Wire output — `domain/schemas.py`

```python
from src.common.bases.schemas import BaseOutput


class BrandOut(BaseOutput):
    id: int
    name: str
    slug: str
    is_active: bool
```

`BaseOutput` is `from_attributes=True` and ships `from_obj()`, `from_objs()`,
`from_dict()`, `from_dicts()`.

### 4. Queries — `infra/repository.py`

**A repository is one statement per method. No branching, no business rules.**
Inherit and you get the whole CRUD surface for free.

```python
from sqlmodel import col, select

from src.common.bases.results import PagedType
from src.infra.postgres.repository.base import PGIDRepository
from src.modules.catalog.brands.domain.models import BrandModel


class BrandRepository(PGIDRepository[BrandModel]):
    async def get_by_slug(self, slug: str) -> BrandModel | None:
        stmt = select(BrandModel).where(col(BrandModel.slug) == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(self, page: int, per_page: int) -> PagedType[BrandModel]:
        stmt = select(BrandModel).order_by(col(BrandModel.id).desc())
        return await self._paginate(stmt, (page - 1) * per_page, per_page)
```

`_paginate` returns the page **and** the total match count. The count is its own
statement (the filters wrapped in a subquery, ordering dropped), which costs a
round-trip and buys a paginator that behaves the same whatever select you hand it —
a window function riding along on the page would have to be added to your statement,
breaking `scalars()` and mis-counting anything that is not a plain `select(Model)`.

### 5. Logic — `app/services.py`

Business rules live here, and only here. `BaseIDService` reads the model off the
generic parameter and gives you guards that raise the framework's typed errors.

```python
from src.common.bases.services import BaseIDService
from src.common.errors.exceptions import ConflictException
from src.core import resources
from src.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from src.modules.catalog.brands.domain.models import BrandModel
from src.modules.catalog.brands.infra.repository import BrandRepository


class BrandService(BaseIDService[BrandModel]):
    def __init__(self, repo: BrandRepository) -> None:
        self.repo = repo

    async def create(self, data: BrandCreate) -> BrandModel:
        if await self.repo.get_by_slug(data.slug):
            raise ConflictException(
                message=f"brand with slug {data.slug} already exists",
                message_code=resources.CONFILICT_ERROR.format("brand"),
                unique_dict={"slug": data.slug},
            )
        return await self.repo.create(BrandModel(**data.to_row(exclude_unset=False)))

    async def update(self, id: int, data: BrandUpdate) -> BrandModel:
        row = self._check_not_empty_dict(data.to_row())
        brand = await self.repo.update_by_id(id, row)
        return self._check_for_id_existence(id, brand)

    async def get_by_id(self, id: int) -> BrandModel:
        return self._check_for_id_existence(id, await self.repo.get_by_id(id))

    async def remove(self, id: int) -> BrandModel:
        return self._check_for_id_existence(id, await self.repo.delete_by_id(id))
```

Guards on `BaseService` / `BaseIDService`:

| Guard | Raises when |
|---|---|
| `_check_for_id_existence(id, obj)` | `obj` is `None` → `NotFoundException` (404), message auto-built from the model name |
| `_check_for_existence(identifier, value, obj)` | same, for a non-id lookup key |
| `_check_not_empty_dict(d)` / `_check_not_empty_list(ls)` | empty input → `ValidationException` (400) |
| `_check_batch_data(input_ids, founded_objs)` | returns a `BatchResultType` splitting found items from per-index `ValidationException`s; raises only if **nothing** was found — this is how partial-success batch endpoints are built |

### 6. The public contract — `interfaces.py`

Other modules may only ever see this.

```python
from typing import Protocol

from src.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from src.modules.catalog.brands.domain.models import BrandModel


class IBrandService(Protocol):
    async def create(self, data: BrandCreate) -> BrandModel: ...
    async def update(self, id: int, data: BrandUpdate) -> BrandModel: ...
    async def get_by_id(self, id: int) -> BrandModel: ...
    async def remove(self, id: int) -> BrandModel: ...
```

### 7. Wiring — `providers.py`

```python
from dishka import Provider, Scope, provide

from src.modules.catalog.brands.app.services import BrandService
from src.modules.catalog.brands.infra.repository import BrandRepository
from src.modules.catalog.brands.interfaces import IBrandService


class BrandProvider(Provider):
    scope = Scope.REQUEST

    brand_repo = provide(BrandRepository)
    brand_service = provide(BrandService, provides=IBrandService)
```

`provide(BrandService, provides=IBrandService)` binds the implementation to the
`Protocol`. Callers depend on `IBrandService`; only this line knows the concrete
class. `BrandRepository`'s `PGUnitOfWork` argument is resolved by `CoreProvider`
— you never construct it.

**This file is the entire registration.** No import into a central module, no list
to append to.

### 8. The endpoint — `routers/admin.py`

```python
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from src.common.types import IdType
from src.modules.catalog.brands.domain.dtos import BrandCreate
from src.modules.catalog.brands.domain.schemas import BrandOut
from src.modules.catalog.brands.interfaces import IBrandService
from src.web.dependencies import Scope, require_access
from src.web.response import APIResponse

router = APIRouter(
    prefix="/brands",
    tags=["Brands"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_access(Scope.BRANDS))],
)

BrandResponse = APIResponse[BrandOut, None]


@router.post("", response_model=BrandResponse)
async def create_brand(
    data: BrandCreate,
    service: FromDishka[IBrandService],
) -> BrandResponse:
    brand = await service.create(data)
    return APIResponse.from_data(BrandOut.from_obj(brand))


@router.get("/{id}", response_model=BrandResponse)
async def get_brand(
    id: IdType,
    service: FromDishka[IBrandService],
) -> BrandResponse:
    brand = await service.get_by_id(id)
    return APIResponse.from_data(BrandOut.from_obj(brand))
```

Two things make this work: **`route_class=DishkaRoute`** (required for
`FromDishka[...]` in handlers) and the fact that a module-level `router` in
`routers/*.py` is all the bootstrapper needs.

### 9. Migrate and run

```bash
alembic revision --autogenerate -m "add brands"
alembic upgrade head
fastapi dev src/web/app.py
```

`POST /brands` is live. At no point did you edit a file outside
`src/modules/catalog/brands/`.

---

## Dependency injection

dishka is the spine. Two scopes matter:

- **`Scope.APP`** — created once per process (connection pools, clients).
- **`Scope.REQUEST`** — created per HTTP request *and* per task execution.

`CoreProvider` ([src/core/provider.py](src/core/provider.py)) makes the whole infra
layer injectable out of the box:

| Inject this | Scope | What you get |
|---|---|---|
| `Settings` | APP | The parsed `config.yml` |
| `PGConnection` | APP | The async engine + session factory |
| `PGUnitOfWork` | **REQUEST** | A session inside a transaction — committed on success, rolled back on exception |
| `ESClient` | APP | Async Elasticsearch client |
| `RedisClient` | APP | Pooled async Redis client |
| `ScheduleSource` | APP | The taskiq Redis schedule source (for scheduling jobs at runtime) |

**The transaction boundary is the request.** `PGUnitOfWork` is entered when the
request scope opens and exits when it closes: your service never calls `commit()`.
If a handler raises, everything it wrote rolls back. Repositories take the UoW in
their constructor and read `uow.session` — which is why a repository is
constructor-injectable with no arguments of your own.

A sub-section of settings can be re-provided as its own type, so a service can
depend on exactly what it needs:

```python
class StorageProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def storage_config(self, settings: Settings) -> StorageConfig:
        return settings.storage

    media_repository = provide(MediaRepository)
    media_service = provide(MediaService, provides=IMediaService)
```

The same container is built by the web app **and** the taskiq broker, so a service
behaves identically whether it was called from an HTTP route or a background job.

---

## The data layer

### Model bases

| Base | Adds |
|---|---|
| `BaseModel` | `to_row()`, and `__tablename__` auto-derived as `tbl_<plural>` |
| `BaseIDModel` | `id` |
| `BaseTimestampModel` | `created_at`, `updated_at` (DB-managed) |
| `BaseIDTimestampModel` | all of the above — the usual choice |

### Repository bases

Pick by the shape of your model: `PGRepository[M]`, `PGIDRepository[M]`,
`PGTimestampRepository[M]`, `PGTimestampIDRepository[M]`. Every write uses
PostgreSQL `RETURNING`, so a create/update/delete hands you back the persisted row
in one round-trip — no `refresh()`, no second SELECT.

**`PGRepository`**

```python
create(data: TModel) -> TModel
bulk_create(data: Sequence[TModel]) -> Sequence[TModel]
get_all() -> Sequence[TModel]
get_all_stream(yield_per: int = 100) -> AsyncIterator[TModel]   # server-side cursor
_paginate(stmt, offset, limit) -> PagedType[TModel]             # page + total match count
_upsert_stmt(data, index_elements) -> ReturningInsert           # INSERT … ON CONFLICT DO UPDATE
_bulk_update_stmt(data, key) -> ReturningUpdate                 # many rows, one UPDATE via a VALUES grid
```

**`PGIDRepository`** adds:

```python
get_by_id(id) -> TIDModel | None
get_by_ids(ids) -> Sequence[TIDModel]
update_by_id(id, row: dict) -> TIDModel | None
update_row_by_id(id, data: TIDModel) -> TIDModel | None
update_by_ids(ids, row: dict) -> Sequence[TIDModel]
upsert_by_id(id, row: dict) -> TIDModel
delete_by_id(id) -> TIDModel | None
delete_by_ids(ids) -> Sequence[TIDModel]
```

**`PGTimestampRepository`** adds `get_stream_by_date_range`,
`update_by_date_range`, `delete_by_date_range`.

**`PGReader`** is the base underneath all of them: the session, and nothing else.
Extend it directly when the code owns no table — a [context module](#context-modules-when-the-module-owns-logic-not-rows)
selecting the few columns its logic needs.

Note the write API takes a **model or a column dict** — never a DTO. The service
converts (`data.to_row()`); the repository stays ignorant of validation.

---

## Responses and errors

Every endpoint returns the same envelope, `APIResponse[Data, Meta]`:

```json
{
  "success": true,
  "message_code": null,
  "data": { "id": 1, "name": "Acme" },
  "meta": { "pager": { "total_items": 57, "total_pages": 3, "has_prev": false, "has_next": true } },
  "error": null,
  "errors": null
}
```

Declare it once per router and reuse:

```python
BrandResponse      = APIResponse[BrandOut, None]      # single or list, no meta
PagedBrandResponse = APIResponse[BrandOut, BaseMeta]  # with pager / filters
```

`data` accepts one item *or* a sequence — the same generic covers both. Helpers:

- `APIResponse.from_data(data, message_code=None, errors=None)` — the success path
  (pass `errors=` for a partial-success batch result).
- `APIResponse.from_external_error(exc)`, `.from_pydantic_error(exc)`,
  `.get_server_error()` — used by the handlers.

Paged responses:

```python
paged = await service.get_paged(page, per_page)
return APIResponse(
    success=True,
    data=BrandOut.from_objs(paged.items),
    meta=BaseMeta(pager=PagerMeta.from_total(page, per_page, paged.total_items)),
)
```

### Errors are raised, never returned

Throw a typed exception from anywhere in the stack; the registered handlers
serialise it into the same envelope with the right status code. Handlers dump with
`exclude_defaults=True`, so an error body carries no `data: null` noise.

| Exception | Status | Carries |
|---|---|---|
| `ValidationException` | 400 | `loc`, `input`, `ctx`, nested child errors |
| `UnAuthorizedException` | 401 | — |
| `ForbiddenException` | 403 | `user_id` |
| `NotFoundException` | 404 | `entity`, `identifier`, `identifier_value` |
| `ConflictException` | 409 | `unique_dict` |
| `TooManyRequestsException` | 429 | `limit`, `remaining`, `retry_after` |

**Every** error leaves in this envelope — there is no second shape for a client to
handle. FastAPI's own `RequestValidationError` is remapped to a 422 (dumped in JSON
mode, so a rejected `Decimal` or date can't break serialisation); Starlette's own
404 and 405 — an unmatched path and a wrong method, which never reach a router —
get the codes `route_not_found` and `method_not_allowed` instead of a bare
`{"detail": ...}`, keeping their headers (a 405 without `Allow` is not really a
405); and any unhandled `Exception` is logged and returned as a generic 500, so
internals never leak.

`message_code` is a stable, machine-readable string that clients switch on. Global
codes live in [src/core/resources.py](src/core/resources.py); each module ships its
own `resources.py` for module-specific codes.

Every log line inside a request is stamped with a request id (taken from an inbound
`X-Request-ID` or generated), and the same id comes back on the response header —
so a 500 in your logs maps to the exact client call.

---

## Authentication and scopes

[src/web/dependencies.py](src/web/dependencies.py) ships a **deliberately generic**
auth layer so the framework has no identity module baked in. It validates a bearer
JWT and checks a `scopes` claim:

```python
router = APIRouter(
    prefix="/brands",
    dependencies=[Depends(require_access(Scope.BRANDS))],   # guard the whole router
)

_guarded = [Depends(require_access(Scope.STORAGE))]          # …or guard per route,
@router.post("", dependencies=_guarded)                      #   leaving others public
```

The JWT contract is `sub` (subject) + `scopes` (a list of strings); a decoded token
becomes a `Principal`, which a handler can also take as a value.

When you build your own identity module, replace the body of `get_current_principal`
with a call to your `IAuthService` and **keep the exported names** (`Scope`,
`Principal`, `require_access`) — every router depends only on those. Add each new
module's scope to the `Scope` enum; the scaffolder does not touch it.

---

## Rate limiting

Two layers, both reading their budgets from `config.yml`, both counting in Redis so
that N workers enforce **one** budget instead of N.

**The floor.** `RateLimitMiddleware` charges `rate_limit.general` against every
request, on every route — including the ones nobody remembered to guard. Successful
responses carry the `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset`
headers, so a client can pace itself instead of discovering the wall.

**The named rule.** Anything expensive or brute-forceable declares its own budget and
asks for it by name, like any other dependency:

```python
from src.infra.ratelimit.dependencies import by_ip, rate_limit

router = APIRouter(prefix="/auth", dependencies=[rate_limit("login")])   # whole router

@router.post("/token", dependencies=[rate_limit("login", (by_ip, by_username))])
async def login(...): ...                                               # …or one route
```

```yaml
rate_limit:
  enabled: true
  trusted_proxies: []          # peers whose X-Forwarded-For may be believed
  general:                     # the blanket rule
    limit: 120
    window_seconds: 60
  rules:                       # what rate_limit("<name>") looks up
    login:   { limit: 5,  window_seconds: 300 }
    refresh: { limit: 20, window_seconds: 60 }
```

A name with no rule in the config is simply **not limited** — a budget is switched
off by deleting it, not by editing a handler. `enabled: false` turns off both layers,
which is what a test suite wants.

**Every key part is charged.** A part maps a request to a bucket; `rate_limit` takes
a sequence of them and spends one call from each:

```python
async def by_username(request: Request) -> str:
    body = await request.json()
    return f"username:{str(body.get('username', '')).strip().lower() or 'unknown'}"

login_rate_limit = rate_limit("login", (by_ip, by_username), closed_when_down=True)
```

`by_ip` alone lets a botnet spread one account's password guesses across a thousand
addresses; `by_username` alone lets one address walk a user list. Charging both meters
both, and the same helper composes any other dimension you need — an admin id, an API
key, a tenant.

**Which way to fail.** When Redis is unreachable the limiter has no counters to judge
by. It fails **open** by default, because losing the cache should not take the API
down with it; a guard on something worth brute-forcing passes `closed_when_down=True`
and gets a refusal instead. Either way the outage is logged, not swallowed.

**Trust nothing you did not put there.** `client_ip` believes `X-Forwarded-For` only
when the immediate peer is listed in `trusted_proxies`. Leave that list empty when
nothing sits in front of the app: an unvetted header is a free way to buy a fresh
bucket per call. Behind a proxy, list the proxy — otherwise every caller in the world
shares one bucket, which is its own kind of outage.

A refusal is a `TooManyRequestsException` (429) carrying `limit`, `remaining` and
`retry_after`, in the same envelope as every other error, with `Retry-After` on the
response. The route guard raises it; the middleware, which sits outside the exception
handlers, assembles the identical body itself.

> The limiter is process-global (`get_limiter()`), not a DI dependency — the
> middleware runs outside the request scope and a `Depends` guard has no container.
> Its Redis connections bind to the loop that first used them, so a test driving the
> app across several event loops should set `enabled: false` or call
> `get_limiter.cache_clear()`.

---

## Background tasks and scheduling

The broker ([src/tasks/broker.py](src/tasks/broker.py)) is a Redis-streams taskiq
broker that **builds the same dishka container as the web app**. So a task gets its
dependencies injected exactly like a route handler does.

Define a task in `<module>/tasks/<anything>.py` — the bootstrapper imports the file,
which registers it:

```python
from dishka.integrations.taskiq import FromDishka, inject

from src.modules.catalog.brands.interfaces import IBrandService
from src.tasks.broker import broker


@broker.task(
    task_name="deactivate_stale_brands",
    queue_name="brands_queue",              # optional: give the task its own stream
    retry_on_error=True,                    # opt in to SmartRetryMiddleware
    schedule=[{"cron": "0 3 * * *"}],       # optional: run it nightly at 03:00
)
@inject(patch_module=True)
async def deactivate_stale_brands(service: FromDishka[IBrandService]) -> int:
    return await service.deactivate_stale()
```

Rules that matter:

- **`@broker.task` outside, `@inject(patch_module=True)` inside.** The broker must
  see the already-injected callable. `patch_module=True` is required.
- Dependencies are `FromDishka[T]` annotations. **A task execution is a REQUEST
  scope**, so it gets its own `PGUnitOfWork` — committed when the task returns,
  rolled back if it raises. Same transactional semantics as an HTTP request.
- **Enqueue from anywhere** with `await deactivate_stale_brands.kiq(arg)` — including
  from a route handler, since the web app imports the broker too.
- **Retries are opt-in.** `SmartRetryMiddleware` runs with `default_retry_label=False`,
  so a task without `retry_on_error=True` is *not* retried on failure. Tune with
  `max_retries` and `delay` labels.
- `queue_name` gives the task its own Redis stream; the broker discovers every extra
  queue at boot and subscribes to it.
- Every log line inside a job is stamped with the task id, exactly as a request is
  stamped with its request id.
- **Results expire after 60 seconds.** A result answers "how did that run just go" —
  a question asked within minutes or not at all. Keeping them forever leaks Redis
  memory, and since Redis runs `noeviction` by default, a full Redis refuses writes:
  the next *enqueue* is what fails, so the queue stalls, not just the cache. Raise
  `result_ex_time` in [src/tasks/broker.py](src/tasks/broker.py) if you need to read
  results back later.

### Scheduling

Two sources are wired into the scheduler, and you can use either:

- **Statically**, with the `schedule=[{"cron": "..."}]` label above (read by
  `LabelScheduleSource`). Accepts `cron`, `cron_offset`, `time` (one-shot), `args`,
  `kwargs`.
- **Dynamically at runtime**, by injecting `ScheduleSource` and calling
  `add_schedule()` / `delete_schedule()`. Schedules live in Redis, so the API process
  can register a job that the scheduler process then runs.

The worker and the scheduler are separate processes:

```bash
taskiq worker    src.tasks.broker:broker
taskiq scheduler src.tasks.scheduler:scheduler
```

### The event bus

For fan-out across modules without coupling them,
[src/tasks/events.py](src/tasks/events.py) provides a small event bus on top of the
same broker. Subscribe a handler class to an event name:

```python
from src.common.bases.events import EventHandler, EventInput
from src.tasks.events import on


class BrandDeactivated(EventInput):      # the payload, a plain pydantic model
    brand_id: int
    reason: str


@on("brand_deactivated")
class ReindexBrandListings(EventHandler[BrandDeactivated]):
    def __init__(self, repo: ListingRepository) -> None:
        self.repo = repo

    async def handle(self, data: BrandDeactivated) -> None:
        ...
```

and emit from anywhere:

```python
from src.tasks.events import emit

await emit("brand_deactivated", BrandDeactivated(brand_id=brand.id, reason="manual"))
```

Each subscriber runs as its own background job on its own queue. A handler must be
registered in its module's `providers.py` (it is resolved from dishka by type) and
must **name its payload in its class header** — `EventHandler[BrandDeactivated]`.
That declaration is the only place the type is written: the bus reads it back off
the class, ships the model as JSON, and validates it into that same type on the
worker, so `handle` receives a model rather than a dict. A handler that names no
payload is refused at registration, not on a worker already holding the job.

The payload is what the event *means*, not a copy of the row — a handler that needs
the current state should still re-read it, because a job runs some time after the
fact. Emitting an event nobody subscribes to is a silent no-op. Declare the event
name constants in `events.py` so emitters and handlers meet on the same vocabulary.

---

## CQRS: the Elasticsearch read side

Scaffolding with `--cqrs` gives you the full read/write split: Postgres stays the
source of truth, Elasticsearch serves the reads, and **projections keep them in
sync automatically**.

Declare the read model in `domain/documents.py` (its index is created on app
startup if missing — a down ES logs a warning and the app still boots):

```python
from elasticsearch.dsl import AsyncDocument, Boolean, Keyword, Text


class BrandDocument(AsyncDocument):
    name = Text()
    slug = Keyword()
    is_active = Boolean()

    class Index:
        name = "brand"
```

Implement the projection in `infra/projections.py` — it reads Postgres and writes
the document:

```python
class BrandProjection(AbstractESProjection[BrandRepository, BrandESRepository]):
    async def project(self, id: int) -> bool:
        brand = await self.pg_repo.get_by_id(id)
        if brand is None:
            return await self.unproject(id)
        doc = BrandDocument(meta={"id": str(brand.id)}, name=brand.name, slug=brand.slug)
        await self.es_repo.save(doc)
        return True
```

(`unproject` is inherited — you only implement `project`.)

Then decorate the write, and sync becomes invisible:

```python
class BrandCreateCommand:
    def __init__(self, repo: BrandRepository) -> None:
        self.repo = repo

    @project(BrandProjection)
    async def execute(self, data: BrandCreate) -> BrandModel:
        return await self.repo.create(BrandModel(**data.to_row(exclude_unset=False)))
```

After `execute` returns, the decorator reads the id off the result and dispatches a
**background taskiq job** on a per-projection queue that reindexes that entity. The
HTTP response is not blocked by Elasticsearch, and a slow index never slows a write.

Five decorators, all from `src/tasks/projection.py`:

| Decorator | Use on | Dispatches |
|---|---|---|
| `@project(P)` | a write returning one entity | `P.project(id)` |
| `@batch_project(P)` | a write returning a sequence | `P.batch_project(ids)` — one job, one bulk index |
| `@unproject(P)` | a delete | `P.unproject(id)` — drops the document |
| `@payload_project(P)` | a write whose return value *is* the data | `P.project(payload)` — no read-back |
| `@batch_payload_project(P)` | ditto, returning a sequence | `P.batch_project(payloads)` |

The id-based four take `id_attr="id"` by default; pass e.g. `id_attr="product_id"`
when the method returns a child row but the *parent* is what must be reindexed.

### Projecting from an id, or from the data itself

`@project` hands the job an **id**, and the job reads the row back out of Postgres
to build the document. That is right whenever the document needs more than the
caller happens to hold.

When the caller has *just computed* every value it wrote — a repricing pass, say —
that read is the same query run twice. `@payload_project` instead hands the job the
model the method **returned**: it is dumped to JSON to cross the queue and rebuilt
inside the job, so the projection writes what it was given. Subclass
`AbstractPayloadProjection` (it takes only an ES repository — there is nothing to
read from) and the payload model is inferred from the generic parameter, which keeps
the two ends from drifting apart:

```python
class ListingPricePayload(BaseModel):
    id: int
    price: Decimal


class ListingPriceProjection(AbstractPayloadProjection[ListingESRepository, ListingPricePayload]):
    async def project(self, payload: ListingPricePayload) -> bool:
        await self.es_repo.bulk_update({str(payload.id): {"price": str(payload.price)}})
        return True


class RepriceCommand:
    @payload_project(ListingPriceProjection)
    async def execute(self, id: int) -> ListingPricePayload:
        ...   # returns the payload; the projection writes exactly it
```

`ESRepository.bulk_update({id: {field: value}})` is the natural partner: it patches
the named fields on many documents in one request, leaving every other field alone —
unlike `save()`, which replaces the whole document.

Reads go through `ESRepository[Doc]`: `save`, `bulk_insert`, `bulk_update`, `get`,
`update`, `delete`, `exists`, and `search()` returning an async DSL `Search`. A shared
`persian_analyzer` is available in [src/infra/es/analyzers.py](src/infra/es/analyzers.py)
— just use it as a field analyzer and the index picks it up on creation.

> **Know the consistency model.** Projection dispatch happens *after* the write
> returns and is not part of its transaction: the read model is **eventually**
> consistent, and there is no outbox. Projection jobs also do not set
> `retry_on_error`, so a failed reindex is dropped rather than retried. If a given
> read model must not drift, add a periodic reconciliation task — or make the
> projection task retryable.

---

## Other infrastructure

**Redis** — inject `RedisClient` and use `.client` for the full async Redis API
(cache, locks, counters). Responses are decoded to `str`.

**Excel** — `ExcelReader` / `ExcelWriter` run openpyxl on a `ProcessPool`, because
parsing or generating a workbook is blocking CPU work that must never touch the event
loop. Rows are typed: declare an `ExcelRow` and columns map by field order.

```python
from src.infra.excel.row import ExcelRow, Row


class BrandRow(ExcelRow):
    name: str = Row(title="Name")
    slug: str = Row(title="Slug")


rows = await reader.read_rows("in.xlsx", BrandRow, start_row=2)      # validated by pydantic
await writer.write_rows("template.xlsx", "out.xlsx", rows, start_row=2, with_titles=True)
```

Reading stops at the first blank row; writing **fills a template** rather than
creating a workbook from scratch. Scaffold with `--excel` to get an
`infra/exporters.py` to house this per module.

**Logging** — `logging.format` picks the handler: `console` gives Rich tracebacks
while you develop, `json` emits one ECS-shaped line per record (`log.level`,
`service.name`, `error.stack_trace`, …) that an ES/Kibana pipeline ingests with no
mapping of its own. Either way the handler is installed on the **root** logger and
uvicorn, gunicorn and taskiq are made to propagate into it, so a server request line
and a service line look alike and carry the same request id. Anything you attach with
`extra=` rides along as its own field:

```python
logger.info("charged %s", order.id, extra={"amount": order.total})
```

**Outbound HTTP** — scaffold with `--http` for an `infra/gateways.py`, the
conventional home for third-party API clients. Map gateway responses into *your*
domain types before they cross back into `app/`.

### Security helpers

[src/common/utils/jwt_utils.py](src/common/utils/jwt_utils.py) and
[src/common/utils/crypto_utils.py](src/common/utils/crypto_utils.py) are
**config-agnostic on purpose**: the caller passes the secret, the algorithm and the
expiry (wire them from `JWTConfig` / `CryptoConfig`). That keeps `common` free of a
`core.config` import and leaves both files unit-testable without a `config.yml`.

**`jwt_utils`** — `create_access_token` / `create_refresh_token` / `decode_token`.
Every token carries `sub`, `iat`, `exp`, a `jti` and a `type`, and `decode_token`
takes an `expected_type`, so a refresh token cannot be replayed as an access token
against a route that forgot to look. Failures come out as the framework's
`UnAuthorizedException` with `token_expired` / `invalid_token` — a raw `PyJWTError`
never escapes, so an expired token answers 401 in the standard envelope rather than
500.

```python
token = create_access_token(str(admin.id), cfg.secret_key,
                            expires_minutes=cfg.access_token_expire_minutes,
                            extra_claims={"scopes": ["brands"]})
payload = decode_token(token, cfg.secret_key, expected_type=TokenType.ACCESS)
```

**`crypto_utils`** — three jobs that are easy to confuse and must not be:

| For | Use | Why that one |
|---|---|---|
| Passwords | `hash_password` / `verify_password` | bcrypt, deliberately slow. The configured salt is applied as an HMAC **pepper**, which also pre-hashes the input and so sidesteps bcrypt's silent 72-byte truncation |
| Payloads you must read back | `encrypt` / `decrypt` | Fernet — authenticated, so a tampered ciphertext raises instead of decrypting to garbage. Any passphrase is stretched to a valid key |
| Opaque tokens (refresh tokens, API keys) | `hash_sha256` + `secure_compare` | Fast and deterministic, so it can be indexed; compared in constant time, so the check leaks no prefix |

A malformed stored hash is a non-match, never an exception — a legacy row cannot take
a login endpoint down.

**`IDEncryption`** ([src/common/bases/encryption.py](src/common/bases/encryption.py))
— exposes a serial primary key as a public id that doesn't announce your row count
(`/orders/42` says how many orders exist; `/orders/43` is a valid guess). It is a
modular multiplication, so it is reversible, stateless and needs no extra column:

```python
public = IDEncryption(mod=10_000_019, coff=387_241, offset=100_000)
public.encode(42)          # -> the id you put in the URL
public.try_decode(value)   # -> None for a malformed id, so the route can 404
```

Obfuscation, not authorisation — keep checking access on every read. It raises rather
than colliding once the table outgrows `mod`, so pick `mod` well above any row count
you expect to reach.

Both ends of the round trip are wired for you, so no handler has to remember either:

```python
ORDER_IDS = IDEncryption(mod=10_000_019, coff=387_241, offset=100_000)

class OrderOut(BaseIDOutput):          # outbound: the serialiser encodes `id`
    __encryption__ = ORDER_IDS

OrderID = Annotated[int, Depends(decode_path_id(ORDER_IDS, "Order"))]

@router.get("/{id}", response_model=APIResponse[OrderOut, None])
async def get(id: OrderID, service: FromDishka[IOrderService]):   # inbound: a row id
    ...
```

The route speaks public ids, the service speaks row ids, and a public id that does
not decode answers **404** — a forged id must be indistinguishable from one that
never existed, or the endpoint becomes an oracle for valid ids.

### Other utilities

`date_utils` (timezone-aware UTC helpers plus Jalali conversion), `persian_utils`
(digit normalisation, rial/toman formatting), `currency_utils` (parses a quoted
amount — Persian digits, separators, float or `Decimal` — into a storable integer or
exact `Decimal`, and raises on anything that is not a number instead of quietly
returning `0`), `string_utils`.

---

## Migrations

Alembic reads its metadata from the bootstrapper, so autogenerate sees every model
in every module with no imports to maintain:

```python
# migrations/env.py
get_bootstrapper().boot_sqlmodels()
target_metadata = SQLModel.metadata
```

```bash
alembic revision --autogenerate -m "add brands"   # after adding/changing a model
alembic upgrade head
alembic downgrade -1
```

The URL comes from `postgresql.dsn` in `config.yml` unless it was set
programmatically (which is how the test suite points it at `test_dsn`). Leave the
placeholder `sqlalchemy.url` in `alembic.ini` alone — it is the sentinel that tells
`env.py` to fall back to the config file.

> The template ships with **no revisions** in `migrations/versions/`. Your first
> `--autogenerate` creates the baseline for whatever modules you have.

---

## Testing

`pytest.ini` sets `asyncio_mode = auto` — every `async def` test just runs, no
marker needed. Tests are auto-marked by folder: `tests/unit` → `unit`,
`tests/integration` → `integration`.

```bash
pytest                      # everything
pytest -m "not integration" # fast, no external services
pytest -m integration       # against the real test database
```

Fixtures in [tests/conftest.py](tests/conftest.py):

| Fixture | Gives you |
|---|---|
| `migrated_test_db` (session) | Drops and recreates the `public` schema of `postgresql.test_dsn`, then runs `alembic upgrade head`. **Refuses to run against a database whose name lacks `test`.** Skips cleanly if the DB is unreachable — but a migration that fails *after* connecting is still reported as a failure. |
| `pg` | A `PGConnection` on the test DSN |
| `uow` | A `PGUnitOfWork` in an open transaction — hand it to a repository directly |
| `clean_db` | Empties every discovered table **and read-model index** between tests |
| `es` | An `ESClient` on the configured hosts |
| `dishka_container` / `dishka_request` | The **real** DI container, with module providers auto-discovered exactly as in production, but pointed at the test DB and a hermetic schedule source that never touches Redis |

Because the container discovers providers through the same bootstrapper, a new
module is testable through DI with **no edit to `conftest.py`** — and for the same
reason `clean_db` empties your new module's table and read-model index without being
told about either. That second half matters: a projected document outlives the row
it came from, so clearing only Postgres would leave a stale document to answer the
next test's search.

---

## Configuration reference

`config.yml` (copy from `config.yml.sample`; gitignored). All eleven sections are
required.

| Section | Keys |
|---|---|
| `fastapi` | `title`, `description`, `version` |
| `postgresql` | `dsn`, `test_dsn`, `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` |
| `taskiq` | `redis_url`, `max_connection_pool_size` |
| `redis` | `url`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `health_check_interval` |
| `rate_limit` | `enabled`, `trusted_proxies`, `general` (`limit`, `window_seconds`), `rules` (name → rule) |
| `es` | `hosts`, `username`, `password`, `api_key`, `verify_certs`, `ca_certs` |
| `jwt` | `algorithm`, `secret_key`, `access_token_expire_minutes`, `refresh_token_expire_minutes`, `api_secret` |
| `crypto` | `encryption_key`, `password_salt` |
| `storage` | `path`, `temp_dir`, `max_file_size`, `allowed_extensions` |
| `csrf` | `secret_key` |
| `logging` | `level`, `format` (`console` \| `json`), `service` |

---

## Reference modules

The `ops` group ships as **living documentation** — real, working modules that
demonstrate the conventions. Read them, then delete or keep them as you see fit.

- **`ops/storage`** — the most complete example: streamed file upload with
  content-hash dedupe, a paged listing, and a public download route. Shows a mixed
  router (per-route guards with one unauthenticated route), a settings sub-section
  re-provided as its own injectable type, `PagedType` + `PagerMeta`, and a
  module-scoped `resources.py`.
- **`ops/jobs`** — inspecting in-flight taskiq jobs.
- **`ops/system`** — health/info endpoints; the smallest possible module.

---

## House rules

These are the conventions the framework and the codebase assume. Breaking them
usually means something silently stops being discovered.

1. **Absolute imports from `src...`** — always.
2. **Every `__init__.py` is empty.** Import from the specific file, never from a
   package root. The bootstrapper relies on this for `routers/` and `tasks/`.
3. **Modules talk through `I*Service` Protocols, never by importing each other.**
4. **A repository holds one statement per method.** All branching, all rules, all
   guards belong in the service.
5. **Input DTOs are `BaseDTO`** (pure pydantic). A repository accepts a model or a
   column dict — never a DTO.
6. **What crosses a module boundary belongs to that module's domain** (its model,
   its `*Out`, its dataclass) — never another module's type.
7. **Raise typed exceptions; never return an error shape.** The handlers own
   serialisation.
8. **Never call `commit()` in a service.** The request scope owns the transaction.
9. **New feature = new module.** If you find yourself editing framework code under
   `src/core` or `src/web` to add a feature, stop and reconsider.
10. **Type parameters are declared inline** — `class Repo[T: BaseModel]`, not a
    module-level `TypeVar` plus `Generic[T]`. The bound belongs at the class that
    enforces it.
11. **The line is 79 columns.** `ruff check` and `ruff format` are the arbiters
    (config in `pyproject.toml`); the scaffolder's output already satisfies both.

---

## License

MIT.
