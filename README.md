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
| Write side / ORM | **SQLModel** + **SQLAlchemy 2.0** (async) | Generic `PGRepository` hierarchy built on `RETURNING`, patch-semantics writes, single-query pagination, bulk upsert/update helpers, a `UnitOfWork` bound to the request |
| Read side / search | **Elasticsearch DSL** (async) | `ESRepository`, index auto-creation on boot, and `@project` / `@batch_project` / `@unproject` decorators that keep the read model in sync with every write |
| Migrations | **Alembic** | Metadata pulled straight from the bootstrapper, so `--autogenerate` sees every module without imports |
| Cache / broker | **Redis** | Pooled async client, injectable |
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
│   │                # BatchResultType, AbstractESProjection
│   ├── errors/      # APPException hierarchy + the *ErrorOut wire schemas
│   ├── utils/       # date / jwt / crypto / string / persian / currency / calc
│   ├── types.py     # validation aliases (IdType, SlugType, RialType, …)
│   ├── enums.py  constants.py
│
├── core/            # The framework's heart
│   ├── bootstrap.py # Auto-discovery: modules, routers, providers, models,
│   │                # ES documents, tasks
│   ├── config.py    # Settings loaded from config.yml (pydantic)
│   ├── provider.py  # CoreProvider — Settings / PG / UoW / Redis / ES / scheduler
│   ├── logger.py    # Rich logger with a request-id ContextVar
│   └── resources.py # Global message codes
│
├── infra/           # Adapters to the outside world
│   ├── postgres/    # models (base + typing), repository (base + typing),
│   │                # connection, uow, column types
│   ├── es/          # client, repository, analyzers
│   ├── redis/       # pooled async client
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
│   ├── dependencies.py # Auth (generic placeholder — swap for your identity module)
│   ├── response.py  # APIResponse envelope
│   ├── error_handlers.py
│   ├── docs.py      # Offline Swagger UI
│   └── middlewares/ # request-id + access logging
│
├── manager.py       # The scaffolding CLI
└── modules/         # Your features live here
    └── ops/{jobs,storage,system}/   # Reference modules — see below
```

**Dependency direction is strictly inward.** `routers` / `tasks` / `app` / `infra`
all depend on `domain`; `domain` knows nothing about HTTP, SQL or Elasticsearch.

---

## The core idea: a module

A feature is a **module**. Modules live under a **group**, which is nothing more
than a namespace folder: `src/modules/<group>/<name>/`.

```
modules/<group>/<name>/
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
**group** and scanned one level deeper. That's the whole rule.

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

Run from the repo root. Pass the name as `<group>.<singular-name>`; the CLI
pluralises the folder, the router prefix, the tags and the table name, while class
names stay singular.

```bash
python -m src.manager module catalog.product           # CRUD (Postgres only)
python -m src.manager module catalog.product --cqrs    # + ES read model, projection, commands/queries
python -m src.manager module catalog.product --tasks   # + tasks/
python -m src.manager module catalog.product --http    # + infra/gateways.py
python -m src.manager module catalog.product --excel   # + infra/exporters.py
```

Flags compose freely (`--cqrs --tasks --excel`). The console script `fastamu` is
also installed by `pip install -e .`, so `fastamu module catalog.product` works too.

What `catalog.product` produces:

| | |
|---|---|
| Folder | `src/modules/catalog/products/` |
| Classes | `ProductModel`, `ProductCreate`, `ProductUpdate`, `ProductOut`, `ProductRepository`, `ProductService`, `IProductService`, `ProductProvider` |
| Table | `tbl_products` |
| Router | `APIRouter(prefix="/products", tags=["products"])` |

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

`_paginate` runs the page **and** its total in a single query, using a
`count(*) OVER ()` window — no second round-trip.

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
_paginate(stmt, offset, limit) -> PagedType[TModel]             # page + total, one query
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

FastAPI's own `RequestValidationError` is remapped into the envelope as a 422, and
any unhandled `Exception` is logged and returned as a generic 500 — internals never
leak.

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
from src.tasks.events import on


@on("brand_deactivated")
class ReindexBrandListings:
    def __init__(self, repo: ListingRepository) -> None:
        self.repo = repo

    async def handle(self, id: int) -> bool:
        ...
```

and emit from anywhere:

```python
from src.tasks.events import emit

await emit("brand_deactivated", brand.id)
```

Each subscriber runs as its own background job on its own queue. A handler must
expose `async def handle(self, id: int) -> bool` and must be registered in its
module's `providers.py` (it is resolved from dishka by type). The bus deliberately
carries **only an entity id** — handlers re-read state rather than trusting a
payload. Emitting an event nobody subscribes to is a silent no-op. Declare the event
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

Three decorators, all from `src/tasks/projection.py`:

| Decorator | Use on | Dispatches |
|---|---|---|
| `@project(P)` | a write returning one entity | `P.project(id)` |
| `@batch_project(P)` | a write returning a sequence | `P.batch_project(ids)` — one job, one bulk index |
| `@unproject(P)` | a delete | `P.unproject(id)` — drops the document |

All take `id_attr="id"` by default; pass e.g. `id_attr="product_id"` when the method
returns a child row but the *parent* is what must be reindexed.

Reads go through `ESRepository[Doc]`: `save`, `bulk_insert`, `get`, `update`,
`delete`, `exists`, and `search()` returning an async DSL `Search`. A shared
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

**Outbound HTTP** — scaffold with `--http` for an `infra/gateways.py`, the
conventional home for third-party API clients. Map gateway responses into *your*
domain types before they cross back into `app/`.

**Utilities** ([src/common/utils/](src/common/utils/)) — `jwt_utils` (create/decode
access + refresh tokens; raises the framework's typed auth errors, never a raw
`PyJWTError`), `crypto_utils` (bcrypt hashing with optional pepper, Fernet
encrypt/decrypt, SHA-256, constant-time compare), `date_utils` (timezone-aware UTC
helpers plus Jalali conversion), `persian_utils` (digit normalisation, rial/toman
formatting), `currency_utils`, `string_utils`.

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
| `migrated_test_db` (session) | Drops and recreates the `public` schema of `postgresql.test_dsn`, then runs `alembic upgrade head`. **Refuses to run against a database whose name lacks `test`.** Skips cleanly if the DB is unreachable. |
| `pg` | A `PGConnection` on the test DSN |
| `uow` | A `PGUnitOfWork` in an open transaction — hand it to a repository directly |
| `clean_db` | Truncates every discovered table between tests |
| `es` | An `ESClient` on the configured hosts |
| `dishka_container` / `dishka_request` | The **real** DI container, with module providers auto-discovered exactly as in production, but pointed at the test DB and a hermetic schedule source that never touches Redis |

Because the container discovers providers through the same bootstrapper, a new
module is testable through DI with **no edit to `conftest.py`**.

---

## Configuration reference

`config.yml` (copy from `config.yml.sample`; gitignored). All nine sections are
required.

| Section | Keys |
|---|---|
| `fastapi` | `title`, `description`, `version` |
| `postgresql` | `dsn`, `test_dsn`, `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` |
| `taskiq` | `redis_url`, `max_connection_pool_size` |
| `redis` | `url`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `health_check_interval` |
| `es` | `hosts`, `username`, `password`, `api_key`, `verify_certs`, `ca_certs` |
| `jwt` | `algorithm`, `secret_key`, `access_token_expire_minutes`, `refresh_token_expire_minutes`, `api_secret` |
| `crypto` | `encryption_key`, `password_salt` |
| `storage` | `path`, `temp_dir`, `max_file_size`, `allowed_extensions` |
| `csrf` | `secret_key` |

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

---

## License

MIT.
