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
fastamu module catalog.product --cqrs
# ✓ created CQRS module 'catalog.products' at shop/modules/catalog/products
```

That's it. The router is live, the service is injectable, the table is in the next
migration, and the ES index is created on boot through discovery.

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

Task backends are optional and configured independently under `tasks`:
`events` uses FastStream, `projection` uses Taskiq/RabbitMQ, and `schedulers`
uses Taskiq/Redis. `app.features` is the enabled feature list; its entries must
match the configured task sections.
`fastamu new shop --cqrs --scheduler --events` selects the corresponding
configuration and dependency extras. With no flags, none of these backends
starts. Event consumers use `fastamu.tasks.events.app:app`.
The API starts publisher connections for enabled backends; it does not start
consumers. Pending SMS records are not automatically dispatched.

## The stack: what each tool does

Fastamu is deliberately not a from-scratch framework. Each concern is delegated
to a mature library; Fastamu's value is the **integration layer** that makes them
behave as one thing.

| Concern | Tool | What Fastamu adds on top |
|---|---|---|
| HTTP, validation, OpenAPI | **FastAPI** | Auto-included routers, a uniform response envelope, typed error handlers, offline (CDN-free) Swagger UI |
| Dependency injection | **dishka** | A `CoreProvider` with the whole infra layer pre-wired; per-module providers discovered and merged automatically; `APP`/`REQUEST` scopes shared identically by the web app *and* the task worker |
| Scheduled jobs & cron | **taskiq** (Redis streams) | A broker that boots the same DI container as the web app, per-module task auto-registration, retry + logging middleware |
| Write side / ORM | **SQLModel** + **SQLAlchemy 2.0** (async) | Generic `DBRepository` hierarchy with dialect-specific SQL, patch-semantics writes, statement-agnostic pagination, bulk upsert/update helpers, a `UnitOfWork` bound to the request |
| Read side / search | **Elasticsearch DSL** (async) | `ESRepository` and index auto-creation on boot |
| Migrations | **Alembic** | Metadata pulled straight from the bootstrapper, so `--autogenerate` sees every module without imports |
| Cache / broker | **Redis** | Pooled async client, injectable |
| Outbound HTTP | **httpx** | One pooled client for the process, plus a `BaseGateway` that owns base url, headers and per-API timeouts |
| Logging | **Rich / orjson** | One switch between Rich console output and ECS-shaped JSON lines, a request id on every record, and uvicorn/gunicorn/taskiq adopted into the same handler |
| Spreadsheets | **openpyxl / xlsxwriter** | Async reader/writer that offloads to a `ProcessPool` so a large workbook never blocks the event loop |
| Validation vocabulary | **pydantic v2** | A shared library of semantic type aliases (`RialType`, `SlugType`, `MobileType`, …) |
| Scaffolding | **typer** | A CLI that generates a complete, correctly-layered module |
| Tests | **pytest** + pytest-asyncio | Async-by-default, real-database fixtures, and a DI container that discovers modules exactly like production does |

---

## Quickstart

**Runtime requirements:** Python **3.13+**, a SQL database (PostgreSQL by default), **Redis**.
Elasticsearch is only needed if you use the CQRS read side.

```bash
# 1) Install the framework and start a project
python3.13 -m venv .venv && source .venv/bin/activate
pip install fastamu
fastamu new shop && cd shop

# 2) Config — config.yml is gitignored; it holds your secrets
#    fill in: db.dsn, db.test_dsn, redis.url,
#             taskiq.redis_url, jwt.secret_key, crypto.encryption_key
pip install -e ".[dev,events,cqrs,scheduler]"

# 3) Schema
alembic upgrade head

# 4) API — your modules, the framework's app
uvicorn fastamu.web.app:app --reload

# 5) Worker + scheduler (separate processes)
taskiq worker    fastamu.tasks.schedulers.broker:broker      # jobs
taskiq scheduler fastamu.tasks.schedulers.scheduler:scheduler # cron
```

`fastamu new` writes only what is yours — a package for your modules, the config
the framework reads, alembic wiring and a test suite. **The framework stays in
site-packages**: there is no vendored copy to keep in step, and upgrading is
`pip install -U fastamu`.

Working *on* Fastamu itself instead? Clone it and `pip install -e ".[dev,events,cqrs,scheduler]"` —
its own `config.yml` points `app.modules` at `fastamu.modules`, so the `ops`
reference modules are what boots.

Swagger UI is served at **`/docs`**, self-hosted from `/static/swagger` — no CDN,
so it works on an air-gapped box.

> **`config.yml` is resolved relative to the current working directory.** Always
> launch from the project root. There is no `.env` / environment-variable override
> layer: the YAML file is the single source of configuration.

---

## Project layout

Two trees: the framework you installed, and the project you generated.

```
# your project — everything here is yours
shop/
├── config.yml       # what the framework reads; app.modules points at yours
├── alembic.ini  migrations/
├── tests/           # the fixtures arrive with the package (see Testing)
└── shop/
    └── modules/     # your features — one folder each
        └── catalog/products/…
```

```
# the installed package — `import fastamu`
fastamu/
├── common/          # Shared models, schemas, errors and general helpers
│   ├── models/      # what an entity is — base.py, fields.py (its columns)
│   ├── schemas/     # what crosses the wire — dtos.py (in), outputs.py (out),
│   │                # meta.py (paging, facets), results.py (PagedType, …)
│   ├── errors/      # base.py, exceptions.py, outputs.py (the *ErrorOut shapes)
│   ├── security/    # passwords.py, crypto.py, tokens.py, ids.py
│   ├── utils/       # dates.py, strings.py, persian.py, currency.py
│   ├── types/       # the shared vocabulary — aliases.py, enums.py, constants.py
│   └── services.py  # BaseService, BaseIDService
│
├── messaging/       # Application messaging and delivery policies
│   ├── calls.py     # Call and shared result-selector wrapping
│   ├── events/      # Immediate event decorators
│   ├── outbox/      # Atomic recording and explicit delivery scope
│   │   └── api.py   # Application-facing outbox decorators and helpers
│   ├── inbox.py     # Explicit consumer deduplication
│   └── retry.py     # RetryPolicy and RetryDecision
│
├── projections/     # Read-model contracts and application decorators
│   ├── base.py      # Single, batch, fanout and deletion projections
│   ├── definition.py # Registration metadata and selector validation
│   ├── decorators.py
│   ├── convertor.py
│   └── errors.py
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
│   ├── db/          # shared repository, connection, uow, table; dialects/
│   ├── es/          # client, repository, analyzers
│   ├── redis/       # pooled async client
│   ├── http/        # pooled httpx client + BaseGateway
│   └── excel/       # ProcessPool-backed reader / writer
│
├── tasks/           # Broker adapters and worker execution
│   ├── events/      # FastStream transport and retry
│   ├── projection/  # Taskiq transport, registration and retry
│   ├── outbox/      # Relay and recovery scheduling
│   └── schedulers/  # Redis jobs, cron and middleware
│
├── web/             # The HTTP layer
│   ├── app.py       # App construction: bootstrap → container → routers
│   ├── dependencies.py # Auth (generic placeholder) + decode_path_id
│   ├── response.py  # APIResponse envelope
│   ├── error_handlers.py
│   ├── docs.py      # Offline Swagger UI
│   └── middlewares/ # request-id + access logging, app-wide rate limit
│
├── manager.py       # The CLI: `fastamu new`, `fastamu module`
├── scaffold.py      # What `fastamu new` writes
├── testing/         # The pytest plugin — fixtures for any project
└── modules/
    └── ops/{jobs,messages,storage,system}/   # Reference modules — see below
```

Adopt the reference modules by naming the package in `config.yml`:

```yaml
app:
  modules:
    - "shop.modules"      # yours, always first
    - "fastamu.modules"   # optional: adds ops/{jobs,messages,storage,system}
```

**Dependency direction is strictly inward.** `routers` / `tasks` / `app` / `infra`
all depend on `domain`; `domain` knows nothing about HTTP, SQL or Elasticsearch.

---

## The core idea: a module

A feature is a **module**: `fastamu/modules/<name>/`. Modules may be filed under a
**group** — `fastamu/modules/<group>/<name>/` — but a group is nothing more than a
namespace folder, and it is entirely optional. `modules/pricing/` and
`modules/catalog/products/` are both perfectly ordinary modules; group things
when grouping earns its keep, not because the layout demands it.

```
modules/[<group>/]<name>/
├── domain/         # The inward core — no I/O, and no idea one exists
│   ├── models.py       # your entities: fields only  (no table, no ORM)
│   ├── dtos.py         # BaseDTO                     (validated input)
│   ├── enums.py
│   └── documents.py    # AsyncDocument  (CQRS only)  (ES read model)
├── app/            # Business logic
│   ├── services.py
│   ├── helpers.py
│   ├── commands.py     # (CQRS only) write commands
│   └── queries.py      # (CQRS only) reads that hit Elasticsearch
├── infra/          # This module's adapters
│   ├── tables.py       # the SQLModel tables carrying domain/models.py
│   ├── repository.py
│   ├── gateways.py     # (--http)  outbound HTTP clients
│   └── exporters.py    # (--excel) file/spreadsheet exporters
├── routers/        # One file per concern (admin.py, public.py, …)
├── tasks/
│   ├── schedulers/  # Taskiq jobs
│   ├── subscribers/ # FastStream subscriber routers
│   └── publishers/  # FastStream publisher routers
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
│   └── enums.py
├── app/services.py  # the engine
├── infra/readers.py # PricingReader — pulls only the columns it needs
├── routers/  interfaces.py  providers.py
```

The reader extends `DBReader` — a repository base with no model bound to it,
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
the bootstrapper ([fastamu/core/bootstrap.py](fastamu/core/bootstrap.py)) finds your code
by walking the app's modules package and looking for exactly five paths.

A package under `fastamu/modules/` is recognised as a **module** if — and only if — it
contains a `domain/` or an `app/` sub-package. Anything else is treated as a
**group** and scanned one level deeper. That's the whole rule — and it is why a
group is optional: `modules/pricing/` is found by the same rule that finds
`modules/catalog/products/`.

| What | Where the bootstrapper looks | What it collects |
|---|---|---|
| **Routers** | `<module>/routers/*.py` | Every module-level `APIRouter` instance (deduped), then `app.include_router(...)` |
| **Providers** | `<module>/providers.py` | Every `dishka.Provider` subclass, instantiated and merged into the container |
| **Tables** | `<module>/infra/tables.py` | Imported so the `table=True` classes register on the shared metadata (this is what Alembic autogenerate sees). Only this file — a `domain/models.py` maps to nothing |
| **ES documents** | `<module>/domain/documents.py` | Every `AsyncDocument` subclass; its index is created on app startup if missing |
| **Schedulers** | `<module>/tasks/schedulers/*.py` | Imported by `boot_schedulers()` to register Taskiq jobs |
| **Subscribers** | `<module>/tasks/events/subscribers/*.py` | Native FastStream routers returned by `boot_subscribers()` |
| **Publishers** | `<module>/tasks/events/publishers/*.py` | Native FastStream routers returned by `boot_publishers()` |

Consequences worth internalising:

- **`routers/` and `tasks/` are packages whose `__init__.py` stays empty.** The
  bootstrapper imports each *file* inside them. Re-exporting from `__init__.py`
  is not just unnecessary, it is against the convention.
- **`providers.py`, `domain/models.py` and `infra/tables.py` are single files**, not packages.
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
fastamu module product                   # CRUD, no group
fastamu module catalog.product           # CRUD, filed under catalog/
fastamu module catalog.product --cqrs    # + ES read model, commands/queries
fastamu module pricing --context         # pure logic: context + reader, no models
fastamu module catalog.product --tasks       # all three task packages
fastamu module catalog.product --scheduler   # only tasks/schedulers/
fastamu module catalog.product --subscriber  # only tasks/events/subscribers/
fastamu module catalog.product --publisher   # only tasks/events/publishers/
fastamu module catalog.product --http    # + infra/gateways.py
fastamu module catalog.product --excel   # + infra/exporters.py
```

Flags compose freely (`--cqrs --tasks --excel`); `--context` is the one exclusion
— a module with no table cannot have a read side to project into, so it rejects
`--cqrs`. The console script `fastamu` is also installed by `pip install -e .`,
so `fastamu module catalog.product` works too.

What `catalog.product` produces:

| | |
|---|---|
| Folder | `fastamu/modules/catalog/products/` |
| Classes | `ProductModel`, `ProductCreate`, `ProductUpdate`, `ProductOut`, `ProductRepository`, `ProductService`, `IProductService`, `ProductProvider` |
| Table | `tbl_products` |
| Router | `APIRouter(prefix="/products", tags=["products"])` |

What `pricing --context` produces:

| | |
|---|---|
| Folder | `fastamu/modules/pricing/` — **not** pluralised; an engine is not a collection |
| Classes | `PricingContext`, `PricingInput`, `PricingOut`, `PricingReader`, `PricingService`, `IPricingService`, `PricingProvider` |
| Table | none — no `infra/tables.py`, no `domain/documents.py` |
| Router | `APIRouter(prefix="/pricing", tags=["pricing"])` |

The group folder is created on first use. Generated files are correctly layered
and cross-imported, with method bodies left as `raise NotImplementedError` — the
wiring is done, the logic is yours.

---

## Tutorial: building a feature end to end

Let's build `catalog.brand` as a plain CRUD module. Start with the scaffold:

```bash
fastamu module catalog.brand
```

### 1. The model — `domain/models.py`

A model declares **fields and nothing else**. It is not the table: no `table=True`,
no ORM base, no `__tablename__`. That is what keeps `domain/` honest — it names
what a brand *is*, and knows nothing about where brands are kept.

```python
from fastamu.common.models.base import BaseIDTimestampModel
from fastamu.common.models.fields import BoolField, CharField


class BrandModel(BaseIDTimestampModel):
    name: str = CharField(35, index=True)
    slug: str = CharField(55, unique=True)
    is_active: bool = BoolField(default=True)
```

`BaseIDTimestampModel` contributes `id`, `created_at` and `updated_at`. Columns use
the **field factories** from
[fastamu/common/models/fields.py](fastamu/common/models/fields.py), which default to
`NOT NULL` — nullability is opt-in, not opt-out.

Bases: `BaseModel` (bare), `BaseIDModel`, `BaseTimestampModel`,
`BaseIDTimestampModel`.

Field factories: `IDField`, `SmallIntField`, `IntField`, `BigIntField`, `BoolField`,
`FloatField`, `NumericField`, `CharField`, `TextField`, `DateField`,
`TimestampField` (timezone-aware), `JSONBField`, `ArrayField` (optional GIN index),
`EnumField` (native PG enum), `ComputedField` (generated column), `ForeignKeyField`.

### 1b. The table — `infra/tables.py`

One line maps the model onto a real table. This file is the *only* place that
knows a database exists, and the only one the bootstrapper imports for metadata:

```python
from fastamu.infra.db.table import BaseTable
from shop.modules.catalog.brands.domain.models import BrandModel


class BrandTable(BrandModel, BaseTable, table=True):
    pass
```

Constraints and indexes that span columns live here too — `__table_args__`, a
`UniqueConstraint`, an explicit `__tablename__`. Repositories are still declared
against the **model** (`DBIDRepository[BrandModel]`) and find the table
themselves, so no layer above `infra/` ever names `BrandTable`.

> **Table naming gotcha.** `__tablename__` is derived as
> `tbl_ + pluralize(ClassName.removesuffix("Table").lower())`. It does **not**
> snake-case, so `ProductTagTable` becomes `tbl_producttags`. Multi-word tables and
> irregular plurals should set `__tablename__` explicitly — as `ops/storage` does
> (`tbl_media`).

### 2. Validated input — `domain/dtos.py`

DTOs are **plain pydantic**, never SQLModel: input validation must not depend on
the ORM. Draw the field types from [fastamu/common/types/aliases.py](fastamu/common/types/aliases.py) so
validation rules stay consistent across the codebase.

```python
from fastamu.common.schemas.dtos import BaseDTO
from fastamu.common.types.aliases import SlugType, StrType


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

### 3. Wire output — `routers/schemas.py`

The shape a client sees is an HTTP concern, so it sits with the routes that
serialise it. Because a model is now plain pydantic, an output can subclass one
instead of restating its fields:

```python
from shop.modules.catalog.brands.domain.models import BrandModel


class BrandOut(BrandModel):
    pass
```

Add computed fields, or narrow to a subset by declaring only what you want — a
schema that must differ from the model still starts from `BaseOutput`:

```python
from fastamu.common.schemas.outputs import BaseOutput


class BrandSummaryOut(BaseOutput):
    id: int
    name: str
```

`BaseOutput` is `from_attributes=True` and ships `from_obj()`, `from_objs()`,
`from_dict()`, `from_dicts()`.

### 4. Queries — `infra/repository.py`

**A repository is one statement per method. No branching, no business rules.**
Inherit and you get the whole CRUD surface for free.

```python
from sqlmodel import col, select

from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.repository import DBIDRepository
from fastamu.modules.catalog.brands.domain.models import BrandModel


class BrandRepository(DBIDRepository[BrandModel]):
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
from fastamu.common.services import BaseIDService
from fastamu.infra.db.transaction import transactional
from fastamu.common.errors.exceptions import ConflictException
from fastamu.core import resources
from fastamu.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from fastamu.modules.catalog.brands.domain.models import BrandModel
from fastamu.modules.catalog.brands.infra.repository import BrandRepository


class BrandService(BaseIDService[BrandModel]):
    def __init__(self, repo: BrandRepository) -> None:
        self.repo = repo

    @transactional
    async def create(self, data: BrandCreate) -> BrandModel:
        if await self.repo.get_by_slug(data.slug):
            raise ConflictException(
                message=f"brand with slug {data.slug} already exists",
                message_code=resources.CONFILICT_ERROR.format("brand"),
                unique_dict={"slug": data.slug},
            )
        return await self.repo.create(BrandModel(**data.to_row(exclude_unset=False)))

    @transactional
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

from fastamu.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from fastamu.modules.catalog.brands.domain.models import BrandModel


class IBrandService(Protocol):
    async def create(self, data: BrandCreate) -> BrandModel: ...
    async def update(self, id: int, data: BrandUpdate) -> BrandModel: ...
    async def get_by_id(self, id: int) -> BrandModel: ...
    async def remove(self, id: int) -> BrandModel: ...
```

### 7. Wiring — `providers.py`

```python
from dishka import Provider, Scope, provide

from fastamu.modules.catalog.brands.app.services import BrandService
from fastamu.modules.catalog.brands.infra.repository import BrandRepository
from fastamu.modules.catalog.brands.interfaces import IBrandService


class BrandProvider(Provider):
    scope = Scope.REQUEST

    brand_repo = provide(BrandRepository)
    brand_service = provide(BrandService, provides=IBrandService)
```

`provide(BrandService, provides=IBrandService)` binds the implementation to the
`Protocol`. Callers depend on `IBrandService`; only this line knows the concrete
class. `BrandRepository`'s `DBUnitOfWork` argument is resolved by `CoreProvider`
— you never construct it.

**This file is the entire registration.** No import into a central module, no list
to append to.

### 8. The endpoint — `routers/admin.py`

```python
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends

from fastamu.common.types.aliases import IdType
from fastamu.modules.catalog.brands.domain.dtos import BrandCreate
from fastamu.modules.catalog.brands.routers.schemas import BrandOut
from fastamu.modules.catalog.brands.interfaces import IBrandService
from fastamu.web.dependencies import Scope, require_access
from fastamu.web.response import APIResponse

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
fastapi dev fastamu/web/app.py
```

`POST /brands` is live. At no point did you edit a file outside
`fastamu/modules/catalog/brands/`.

---

## Dependency injection

dishka is the spine. Two scopes matter:

- **`Scope.APP`** — created once per process (connection pools, clients).
- **`Scope.REQUEST`** — created per HTTP request *and* per task execution.

`CoreProvider` ([fastamu/core/provider.py](fastamu/core/provider.py)) makes the whole infra
layer injectable out of the box:

| Inject this | Scope | What you get |
|---|---|---|
| `Settings` | APP | The parsed `config.yml` |
| `DBConnection` | APP | The async engine + session factory |
| `DBUnitOfWork` | **REQUEST** | An open session; application operations own commit/rollback |
| `ESClient` | APP | Async Elasticsearch client |
| `RedisClient` | APP | Pooled async Redis client |
| `ScheduleSource` | APP | The taskiq Redis schedule source (for scheduling jobs at runtime) |

**The transaction boundary is an application operation.** Dishka opens a
`DBUnitOfWork` when it is first resolved and closes it at scope exit. Scope exit
never commits. SQLAlchemy discards any outstanding transaction when the session
closes. Repositories only use `uow.session`; they do not own the transaction.

Use `@transactional` on a writing application method. It requires an open UoW,
commits before returning, and rolls back on an exception or cancellation before
commit. Nested decorated calls join the outer operation; only its owner commits.
A failed nested operation marks the outer transaction rollback-only even if its
exception is caught. Do not manually commit/rollback or use savepoints inside
this boundary. Concurrent operations need separate UoWs; a child task cannot
borrow an inherited application transaction.

```python
from fastamu.infra.db.transaction import transaction, transactional
from fastamu.infra.db.uow import DBUnitOfWork

@transactional
async def rename_product(repo, product_id, title):
    return await repo.update_by_id(product_id, {"title": title})

# Outside Dishka, open a session and use an explicit operation boundary:
async with DBUnitOfWork(database) as unit:
    async with transaction():
        await unit.session.execute(statement)
```

The UoW has no message callbacks, version allocation or broker operations.
HTTP error handlers only format errors; they never resolve a database session
or perform rollback. This also covers errors translated into HTTP responses:
uncommitted work is discarded at session close.

### Messaging package imports

Messaging APIs moved out of `common`; projections now have their own package.
Update application imports to these paths (the old paths are removed):

```python
from fastamu.messaging import Call, inbox
from fastamu.messaging.events.decorators import event
from fastamu.messaging.outbox import api as outbox
from fastamu.messaging.retry import RetryPolicy
from fastamu.projections.base import AbstractProjection
from fastamu.projections.decorators import projection
```

`messaging.outbox.api` explicitly loads application helpers. Importing
`messaging.outbox.message` only loads the message contract; it does not
initialize SQL or task transports. Transport adapters remain in `tasks`, and
SQL persistence remains in `infra/db`. This package refactor does not change
commit timing, retry budgets, queue names or wire payloads.

### Independent events, projections and transactions

`@transactional` in `infra/db/transaction.py` manages SQL only. It neither
inspects messages nor dispatches them. Event declarations live in
`messaging/events/`, projection declarations in `projections/`, and the
shared result-selector helper in `messaging/calls.py`. Each message decorator
awaits its wrapped call, selects the result, and publishes through its own
transport adapter. Message decorators work without a UoW or transaction.

To publish after a method's SQL commit, put message decorators **outside**
`@transactional`:

```python
from fastamu.messaging.events.decorators import event, emit
from fastamu.projections.decorators import (
    projection, batch_projection, fanout_projection, unprojection,
)
from fastamu.infra.db.transaction import transactional

@event("catalog.product.created", payload=lambda call: ProductCreated(
    product_id=call.result.id,
    title=call.result.title,
))
@projection(ProductProjection, id=lambda call: call.result.id)
@transactional
async def create_product(repo, data):
    return await repo.create(ProductModel(**data.to_row()))
```

Execution is body → commit → projection → event. For directly decorated HTTP
endpoints, keep `@router.post(...)` and `@inject` above these decorators so
Dishka opens the UoW before the transaction. Decorating an injected service's
application method is usually simpler.

The caller owns composition. Putting `@transactional` outside message decorators
sends messages before commit. A nested transactional call joins its parent's SQL
transaction; message decorators around that nested call publish when it returns,
**before the outer commit**. Put publication at the actual outer boundary when
it must follow commit. Decorators do not validate or rearrange their order.

Selectors are synchronous functions, commonly lambdas. `call.result` is the
method's result; `call.arguments` is a read-only mapping of parameter names to
supplied values, including defaults. A delete returning `None` can use
`@unprojection(ProductUnProjection, id=lambda call: call.arguments["product_id"])`.
For an event, return a Pydantic model or `None` to skip it. Each projection
decorator enforces its own concrete class and selector contract:

| Decorator | Class | Selector result | Publication |
| --- | --- | --- | --- |
| `projection(..., id=...)` | `AbstractProjection` | One integer | One task |
| `batch_projection(..., ids=...)` | `AbstractBatchProjection` | Sequence of integers | One batch task |
| `fanout_projection(..., id=...)` | `AbstractFanoutProjection` | One integer | One task building multiple documents |
| `unprojection(..., id=...)` | `AbstractUnProjection` | One integer | One deletion task |

Single, fanout and deletion decorators reject lists, including empty lists. Batch
validates every ID before sending, deduplicates in input order, and skips empty
sequences. A list is never expanded into individual messages. Successful
decorators return the original result unchanged.

```python
@batch_projection(ProductBatchProjection, ids=lambda call: call.result)
@transactional
async def update_products(...):
    ...
    return product_ids

@unprojection(ProductUnProjection, id=lambda call: call.arguments["product_id"])
@transactional
async def delete_product(product_id: int):
    ...
```

Selectors and JSON serialization run after the wrapped call returns. With the
order above they run after commit, so their failures cannot roll back that write.
Load required fields and flush database-generated IDs before returning. Inner
decorators publish first. Any selector or transport error propagates immediately:
later sends and outer decorators do not run, and earlier sends remain delivered.
There is no error aggregation or automatic retry.

For explicit publication, use `await emit(subject, model)` or
`await publish(ProjectionClass, argument)` from
`fastamu.tasks.projection.publisher`. The transport adapter expects one ID or
one batch matching the task contract. Both publish immediately and need no SQL
scope. For a cache invalidation or a custom publisher, explicitly await it after
the outer transaction completes:

```python
async with transaction():
    result = await update_product(...)
    key = result.cache_key
await cache.delete(key)
```

This assumes the scope owns the transaction; a scope joining an existing
transaction does not commit it. The old message buffer, `after_commit` callback
API, dispatcher, message records and `PostCommitDeliveryError` are removed.
`emit` is now async. The generic `enqueue` helper is removed; use the matching
projection decorator or call the projection publisher explicitly.

These immediate decorators have no durability or automatic retry. A crash or
publication failure after commit can lose messages. Use the optional outbox
below for durable SQL-to-broker publication. Retrying the entire business
operation can repeat writes and already delivered messages.

Broker lifecycle is still required. For standalone publishers start
`fastamu.tasks.lifespan.task_lifespan()` first. Event subscriptions use native
FastStream routers; each subscriber that writes SQL can call a transactional
application method. Redis events use Pub/Sub, not a durable queue.

### Optional transactional outbox

The outbox uses relational transactions and RabbitMQ. It is opt-in per operation:
the immediate event/projection decorators above keep their existing behavior.
`transactional` and the UoW still manage SQL only.

```python
from fastamu.messaging.outbox import api as outbox
from fastamu.infra.db.transaction import transactional

class ProductBatchProjection(AbstractBatchProjection):
    outbox_name = "catalog.products.project"  # stable across code moves
    # Existing projection implementation and queue configuration.

@outbox.deliver
@transactional
@outbox.batch_projection(ProductBatchProjection, ids=lambda call: call.result)
async def update_products(...):
    ...
    return product_ids
```

The inner decorator serializes and inserts the message after the method returns,
inside the business transaction. SQL and the message commit together; selector,
serialization or insert errors roll both back. The outer `outbox.deliver` then
awaits immediate publication. A broker failure leaves the committed message
pending and is logged; it does not turn the committed operation into a failed
business response. Use an open UoW, and put delivery outside the outermost SQL
transaction. Nested delivery scopes join the outer scope.

The matching tools are `outbox.event(subject, payload=...)`,
`outbox.projection(..., id=...)`, `outbox.batch_projection(..., ids=...)`,
`outbox.fanout_projection(..., id=...)` and `outbox.unprojection(..., id=...)`.
Every persisted projection must explicitly declare a unique `outbox_name` and
be registered at publisher startup. Preserve that name while pending messages
exist. A batch projection is one message containing multiple source IDs; a
recovery batch below groups outbox messages, independently of their payloads.

For explicit composition, surround `async with transaction()` with
`async with outbox.delivery()`, and call `record_event`, `record_projection` or
`record_batch_projection` inside the transaction. Recording alone is supported
when only scheduled recovery is desired.

```yaml
tasks:
  # Existing RabbitMQ event/projection and Redis scheduler settings also apply.
  outbox:
    polling: true
    poll_interval: 20
    batch_size: 1000
    max_parallel_batches: 10
    concurrency: 4
```

Create `fastamu_outbox`, `fastamu_outbox_batches` and `fastamu_outbox_control` through your application's
migration before enabling this configuration. Their definitions live in
`fastamu.infra.db.outbox.table` and join SQLModel metadata when outbox is enabled;
application startup does not create or migrate them automatically.
The control table needs exactly one row, with `id=1`; include its insert in
the migration. SQLAlchemy table creation seeds it automatically. The test
harness preserves this control row when clearing application data.

Recovery is an interval task on the existing Taskiq scheduler, with no permanent
relay loop. Run both the scheduler and its worker. The worker must initialize
the configured RabbitMQ event/projection publishers and projection registry in
its startup hooks, and close them at shutdown. Goldis provides these hooks in
`src.run.scheduler`; its worker target is `src.run.scheduler:broker`.

Each tick reserves at most 10,000 eligible messages, split into jobs of at most
1,000: zero messages produce zero jobs, 1–1,000 produce one, and 5,000 produce
five. Queued and running reservations share the cap of ten across ticks and
coordinators. Jobs run in parallel subject to worker capacity; each publishes
at most four messages concurrently. The planner fetches bounded IDs instead of
counting the whole outbox. It orders selection by readiness time and ID; neither
parallel publication nor consumer execution guarantees business ordering.

Short SQL claims keep the immediate sender and recovery jobs from owning the
same ready message simultaneously. Network publication holds no SQL connection.
Reservation transactions serialize on the control row using a normal SQL
update. This replaces PostgreSQL advisory locks and SKIP LOCKED, and can wait
for a conflicting SQL lock. The database and driver must support transactions
and accurate affected-row counts; there is no database-name allowlist. Runtime
concurrency tests cover PostgreSQL, MySQL and SQLite. Other engines require
validation in their deployment environment. Database clock values are bound
as query parameters so ready-message predicates remain indexable.
Immediate delivery passes only one concurrency-sized group of IDs per claim.
Confirmed messages in each group share one SQL delete/commit, with ownership
checked per message. A slow send can delay recording the other confirmations
in its group until that send completes or times out.
Batch reservations expire after 60 seconds and renew while jobs claim work;
message claims expire after 30 seconds, with a five-second publish timeout.
Lost queued jobs and crashed workers become recoverable after expiry. Broker
failures are rescheduled with bounded exponential delay and jitter. Consumer
retry is configured separately using the policies described below.

`polling: false` disables automatic recovery while preserving immediate delivery.
To trigger recovery immediately with polling enabled, enqueue the registered
`fastamu.outbox.recover` task through the application's initialized scheduler
broker. It uses the same batch jobs and worker dependencies as a scheduled tick.
A tick can leave backlog, delayed messages, and live reservations for later ticks.
Twenty seconds is a scheduling interval, not a maximum recovery latency.

Each message retains its UUID as the RabbitMQ message ID / Taskiq task ID.
Broker confirmation precedes deletion from SQL. A crash between those
steps can publish the same ID again: **this is at-least-once publication, not
deduplication or exactly-once processing**. Consumers still need idempotency
where duplicates matter. Deletion follows broker acceptance, not successful
projection execution. Elasticsearch versions are unchanged.

Operational costs include outbox inserts and claim/result updates, WAL and
index maintenance, scheduler queue traffic, and broker confirms. Recovery
concurrency is bounded separately from concurrent application requests. Monitor
pending count and oldest pending age, `attempts`, `last_error`, and active batch
reservations. Confirmed rows are deleted; pending rows are never automatically
discarded. A live `claim_token` with a future `available_at` means publication is
in progress. An absent or expired claim means pending work, subject to its next
available time. No redundant status column or sent-message history is stored.

### SQL consumer inbox

Enable `tasks.inbox: true` and migrate `fastamu_inbox` before using the optional
tools in `fastamu.messaging.inbox`. The primary key is `(consumer, message_id)`;
receipts contain no payload and are committed with the SQL business effects.
Use a stable consumer name and the original broker message ID on every attempt.
Never generate a replacement ID in the consumer. Missing/empty IDs are errors.

```python
from fastamu.messaging import inbox
from fastamu.infra.db.transaction import transactional

@transactional
@inbox.consumer("inventory.stock.apply", message_id=lambda call: call.arguments["message_id"])
async def handle(data, *, message_id: str):
    await repository.apply(data)
```

The selector runs before the handler (`call.result` is None). A committed
duplicate skips the handler and returns None; it does not replay a cached
return value. Native FastStream routers can pass `RabbitMessage.message_id` to
this application method. Acknowledge only after the outer SQL transaction
commits. Application policies decide retry behavior; transport middleware
executes those decisions. No custom Taskiq receiver is introduced.

For explicit control, inside an existing `transaction()` use
`async with inbox.consume(consumer_name, message_id) as execute` and run the SQL
effects only when `execute` is true. Concurrent duplicates contend on the
database's unique key. `InboxRepository.claim` uses the dialect's targeted
`ON CONFLICT DO NOTHING RETURNING` on PostgreSQL and SQLite; new receipts take
one statement without a savepoint. MySQL/MariaDB and other dialects use an
insert with a savepoint fallback. MySQL's no-op upsert cannot reliably identify
the insert winner with SQLAlchemy's FOUND_ROWS setting, and `INSERT IGNORE`
can suppress unrelated errors, so neither is used for inbox claims.

The repository neither commits nor flushes pending ORM changes. Business failures
or cancellation roll back the receipt with the outer transaction. SQLite uses
modern transaction control (Python 3.13 as required by the package). The
fallback needs transactional savepoints; unknown SQLAlchemy dialects do not
need a Fastamu adapter to use it. A duplicate requires an additional exact-key
lookup; a locking read avoids stale snapshots on MySQL.

Use case-sensitive identity columns. If the database collation conflates two
different IDs, the repository raises instead of silently skipping the new message.
Keep receipts for the full retry/redelivery/manual replay horizon. They are not
deleted when the originating outbox row disappears; purging them permits those
identities to execute again. No automatic inbox expiry is configured.

The inbox covers effects in the same SQL transaction. HTTP, email, Redis and
Elasticsearch are separate systems and need their own idempotent operations or
another outbox. Elasticsearch projections should write deterministic document
IDs and assign current values instead of incrementing them. Replay tests cover
single writes, deletions and partial batch/fanout failures. This does not solve
out-of-order updates or reconciliation racing with newer source changes.

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

In `fastamu.common.models.base` — all pure, none of them a table:

| Base | Adds |
|---|---|
| `Base` | `to_row()`, `to_dict()`, `to_json()`, `patch()`, `from_obj()`, `from_objs()`, … |
| `BaseModel` | nothing — the plain entity base |
| `BaseIDModel` | `id` |
| `BaseTimestampModel` | `created_at`, `updated_at` (DB-managed) |
| `BaseIDTimestampModel` | all of the above — the usual choice |

`BaseTable`, in `fastamu.infra.db.table`, is what turns one into a
table, and it is the only base that carries a `__tablename__`.

### Repository bases

Pick by the shape of your model: `DBRepository[M]`, `DBIDRepository[M]`,
`DBTimestampRepository[M]`, `DBTimestampIDRepository[M]`. Every write uses
native `RETURNING` where supported, or locks and re-reads rows inside the same
transaction where it is not. The public repository is `DBRepository`, with
`DBIDRepository`, `DBTimestampRepository`, and `DBTimestampIDRepository` variants.
Connection, unit of work, and table definitions are shared in `infra/db`;
backend-specific SQL lives in `infra/db/dialects`.

A repository is parameterised by the **model**, and locates the table that carries
it — the class in `infra/tables.py` that subclasses it with `table=True`. Nothing
above `infra/` mentions a table class, and a model that no table carries raises an
error naming the file to declare it in.

**`DBRepository`**

```python
create(data: TModel) -> TModel
bulk_create(data: Sequence[TModel]) -> Sequence[TModel]
get_all() -> Sequence[TModel]
get_all_stream(yield_per: int = 100) -> AsyncIterator[TModel]   # server-side cursor
_paginate(stmt, offset, limit) -> PagedType[TModel]             # page + total match count
_upsert_stmt(data, index_elements) -> ReturningInsert           # INSERT … ON CONFLICT DO UPDATE
_bulk_update_stmt(data, key) -> ReturningUpdate                 # many rows, one UPDATE via a VALUES grid
```

**`DBIDRepository`** adds:

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

**`DBTimestampRepository`** adds `get_stream_by_date_range`,
`update_by_date_range`, `delete_by_date_range`.

**`DBReader`** is the base underneath all of them: the session, and nothing else.
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
codes live in [fastamu/core/resources.py](fastamu/core/resources.py); each module ships its
own `resources.py` for module-specific codes.

Every log line inside a request is stamped with a request id (taken from an inbound
`X-Request-ID` or generated), and the same id comes back on the response header —
so a 500 in your logs maps to the exact client call.

---

## Authentication and scopes

[fastamu/web/dependencies.py](fastamu/web/dependencies.py) ships a **deliberately generic**
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

`fastamu.web.ratelimit` connects `throttled-py` to HTTP. The library owns the
sliding-window algorithm and atomic Redis operations; `RateLimitProvider` borrows
the existing app Redis client and pool. Standalone FastAPI apps must register
`RateLimitProvider()` alongside `CoreProvider()` in their Dishka container.

Two layers, both reading their budgets from `config.yml`, both counting in Redis so
that N workers enforce **one** budget instead of N.

**The floor.** `RateLimitMiddleware` charges `rate_limit.general` against every
request, on every route — including the ones nobody remembered to guard. Successful
responses carry the `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset`
headers, so a client can pace itself instead of discovering the wall.

**The named rule.** Anything expensive or brute-forceable declares its own budget and
asks for it by name, like any other dependency:

```python
from fastamu.web.ratelimit import by_ip, rate_limit

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
a sequence of them and checks their Redis buckets concurrently. All checks finish
before a refusal is returned; this is not an all-or-nothing multi-bucket transaction:

```python
from fastamu.web.ratelimit import by_body_field, by_ip, rate_limit

login_rate_limit = rate_limit(
    "login", (by_ip, by_body_field("username")), closed_when_down=True
)
```

`by_body_field` covers the common case; write your own `KeyPart` for anything else
(an admin id, an API key, a tenant) — it is just `async (Request) -> str`.

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

A route guard reads its budgets from **the container serving the request**, falling
back to `config.yml` when there is none (the middleware, which runs outside the
request scope). So a test app built on other settings is limited by *its* rules:
override `rate_limit` in a test provider and the guard follows, no patching. Limiters
are kept per Redis url in `_limiters` — clear it between tests that swap stores.

---

## Background tasks and scheduling

The broker ([fastamu/tasks/schedulers/broker.py](fastamu/tasks/schedulers/broker.py)) is a Redis-streams taskiq
broker that **builds the same dishka container as the web app**. So a task gets its
dependencies injected exactly like a route handler does.

Define a task in `<module>/tasks/schedulers/<anything>.py` — the bootstrapper imports the file,
which registers it:

```python
from dishka.integrations.taskiq import FromDishka, inject

from fastamu.messaging.retry import RetryPolicy
from fastamu.modules.catalog.brands.interfaces import IBrandService
from fastamu.tasks.schedulers.broker import broker


@broker.task(
    task_name="deactivate_stale_brands",
    queue_name="brands_queue",              # optional: give the task its own stream
    retry_policy=RetryPolicy(),             # opt in; choose an application policy
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
  scope**, so it gets its own `DBUnitOfWork`. Writing application methods use
  `@transactional`, with the same commit/rollback semantics as in HTTP handlers.
- **Enqueue from anywhere** with `await deactivate_stale_brands.kiq(arg)` — including
  from a route handler, since the web app imports the broker too.
- **Retries are opt-in.** Declare `retry_policy=RetryPolicy(...)` on the task.
  The worker reads the registered policy, not a policy supplied in message labels.
  Retries are saved to the Redis schedule source; the scheduler process must run.
  Old `retry_on_error`, `max_retries` and `delay` labels do not configure this policy.
- `queue_name` gives the task its own Redis stream; the broker discovers every extra
  queue at boot and subscribes to it.
- Every log line inside a job is stamped with the task id, exactly as a request is
  stamped with its request id.
- **Results expire after 24 hours by default.** A result answers "how did that run just go" —
  a question asked within minutes or not at all. Keeping them forever leaks Redis
  memory, and since Redis runs `noeviction` by default, a full Redis refuses writes:
  the next *enqueue* is what fails, so the queue stalls, not just the cache. Raise
  `tasks.schedulers.result_ex_time` in configuration if you need to read
  results back later.

### When work fails

The application chooses a policy for each job. Scheduled retries use the same
`RetryPolicy.decide(error, attempt)` contract as events and projections:

```python
@broker.task(retry_policy=RetryPolicy(max_attempts=3, delays=(30,), jitter=0))
async def refresh_rates() -> None: ...
```

### Application retry policies

`fastamu.messaging.retry.RetryPolicy` owns error classification, the attempt budget
and delay. Both event and projection adapters call `decide(error, attempt)`;
Taskiq does not apply a second budget or an additional exception filter.

```python
from fastamu.messaging.retry import RetryDecision, RetryPolicy

projection_policy = RetryPolicy(
    max_attempts=5,                   # includes the initial execution
    delays=(5, 30, 120, 600),         # seconds; last delay repeats if needed
    jitter=0.1,                      # adds up to 10%; zero disables it
    retry_on=(ConnectionError, TimeoutError),
    stop_on=(),
)

class ProductProjection(AbstractProjection):
    queue_name = "products"
    retry_policy = projection_policy
    # Implement the projection's query methods.

class EventPolicy(RetryPolicy):
    def decide(self, error, attempt):
        # Application-specific classification can inspect error attributes.
        if isinstance(error, ConnectionError) and attempt < 4:
            return RetryDecision(delay=30, max_delay=30)
        return RetryDecision()       # terminal failure
```

The default policy allows five total attempts for `Exception`, with delays
5/30/120/600 seconds and 10% jitter. Choose narrower error classes for your
application; `ValueError` and `TypeError` are not unconditionally excluded.
Cancellation is propagated and does not consume the failure budget. A custom
`decide` implementation owns its own bounds. For randomized delays, return a
stable `max_delay` bucket to avoid creating a queue for every random value.

Native FastStream routers remain responsible for event subscriptions:

```python
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitQueue, RabbitRouter
from fastamu.core.config import get_settings
from fastamu.tasks.events.broker import broker
from fastamu.tasks.events.retry import EventRetry

retry = EventRetry(
    broker,
    {"inventory.events": EventPolicy()},
    config=get_settings().tasks.events.retry,
)
router = RabbitRouter(middlewares=[retry], ack_policy=AckPolicy.MANUAL)

@router.subscriber(RabbitQueue("inventory.events", durable=True))
async def inventory_changed(data: dict):
    ...
```

Event policies are per subscriber queue; projection policies are per class/task.
Use manual acknowledgement on an event router whose subscriptions all have a
policy. Subscribers without a policy retain their native behavior. EventRetry
supports RabbitMQ; it does not add retry support to the Redis event transport.

For RabbitMQ, each failure is confirmed in a persistent retry or failed queue
before the original delivery is acknowledged. Retry queues use TTL and quorum
at-least-once dead-lettering back to the original queue. This also avoids
re-emitting an event to subscribers that already succeeded. Exhausted messages
remain in a failed queue until explicitly replayed or removed. Repair the cause,
then call `await retry.replay_failed(queue, limit=100)` for events, or
`await projection_broker.replay_failed(queue, limit=100)` for projections.
Replay preserves the message ID and resets the attempt counter; it confirms
publication before acknowledging the failed copy. Invalid wire messages and
unknown projection tasks are quarantined; they may need repair before replay.

Operational settings are independent of application policy:

```yaml
tasks:
  projection:                      # also available under events / schedulers
    retry:
      namespace: fastamu
      publish_timeout: 5
      handoff_failure_delay: 1      # bounded pause before transport redelivery
      error_max_length: 2048
      replay_batch_size: 100
```

RabbitMQ publisher confirms, persistent delivery and safe quorum dead-lettering
are correctness requirements. These are not optional policy toggles. Scheduled
Redis jobs instead store delayed retries in the existing schedule source;
terminal errors use the configured result backend, not RabbitMQ failed queues.

Capacity and correctness limits:

- The default policy creates at most four waiting queues plus one failed queue
  per destination, lazily. Quorum replication and retained failures cost disk,
  memory and broker work. Old delay buckets are not automatically removed.
- A handoff failure pauses for `handoff_failure_delay` before requeueing only
  the affected delivery. It does not reopen the consumer channel. This bounds
  repeated rejection traffic, but occupies that delivery's prefetch slot.
- Waiting for the retry delay happens in RabbitMQ/Redis, not in a sleeping
  handler. Missing RabbitMQ destinations can add the broker's own dead-letter
  retry interval to the delay. Per-message TTL jitter may cause head-of-line
  waiting within its delay bucket.
- Projection prefetch 1 and single-active-consumer serialize each queue;
  separate queues run concurrently. The retry-enabled listener also validates
  and re-encodes the envelope once before native Taskiq processing.
- The existing Redis schedule source scans stored schedules and is deprecated
  upstream. A large scheduled-retry backlog increases that scan cost; migration
  of existing schedules needs its own change.
- Confirm-then-ACK can still duplicate after a crash. Use inbox/idempotent writes;
  attempt limits count logical retries, not every possible crash redelivery.
  Retrying a batch repeats its whole payload. Retry does not preserve ordering
  or prevent an older projection from overwriting newer data.

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
taskiq worker    fastamu.tasks.schedulers.broker:broker      # jobs
taskiq scheduler fastamu.tasks.schedulers.scheduler:scheduler # cron
```

## CQRS: the Elasticsearch read side

The `--cqrs` scaffold supplies document, repository, command and query files.
Events and projections can be declared on transactional application methods.
Existing pending SMS records are not automatically dispatched.

Projection contracts live in `fastamu/projections/`:

- `convertor.Convertor[Model, Document]`: implements the synchronous
  `convert(model)` method. Conversion has no database or messaging I/O.
- `base.AbstractProjection[Model, Document]`: accepts a convertor instance.
  Implements `project(id)` using `_db_query(id) -> Model | None`, conversion,
  and `_es_query(document)` for a single destination write.
- `base.AbstractBatchProjection[Model, Document]`: accepts a convertor instance.
  Implements `batch_project(ids)` using `_db_query(ids) -> Sequence[Model]`
  and `_es_query(documents)` for bulk writes. It does not call single-item
  projections.
- `base.AbstractUnProjection`: implements `unproject(id)` using the abstract
  `_es_query(id)` deletion method. No source model is required.
- `decorators.projection`: publish one ID for a single projection.
- `decorators.batch_projection`: publish one list for a batch projection.
- `decorators.unprojection`: publish one ID for a deletion.
- `decorators.fanout_projection`: publish one source ID for multiple documents.
- `base.AbstractFanoutProjection`: one source ID can produce many documents.

Define concrete classes in `<module>/infra/projections.py`, or import them there. Set `queue_name` on each class (it can also
be inherited from a shared base). Register the class and its dependencies in
Dishka providers with REQUEST scope. Example:

```python
class ProductProjection(AbstractProjection[Product, ProductDocument]):
    queue_name = "product_projection_queue"
    # Implement _db_query and _es_query.

class ProductBatchProjection(AbstractBatchProjection[Product, ProductDocument]):
    queue_name = "product_projection_queue"
    # Implement the two bulk query methods.

from fastamu.tasks.projection.publisher import publish

await publish(ProductProjection, product_id)
await publish(ProductBatchProjection, product_ids)
```

Subclass creation records the definition; bootstrap registers Taskiq tasks
and queue definitions once. There is **one projection broker with multiple
queues**, and multiple named tasks can share a queue. Publishing only calls
Taskiq's `kiq`; it never declares a queue or resolves a projection instance.
Queue declaration happens on broker startup (including publisher startup).

```yaml
tasks:
  projection:
    broker: rabbitmq
    url: amqp://guest:guest@localhost:5672/
    prefetch: 1
```

CQRS also requires the `es` connection configuration. Run the worker with:

```bash
fastamu projection-worker
```

This command uses Taskiq's standard receiver. Each queue is durable with
single-active-consumer and RabbitMQ prefetch 1. Different queues can execute
concurrently. Dishka supplies a fresh request scope for each execution.

Projection retry is opt-in through the class's `retry_policy`. Without one,
execution errors retain Taskiq's normal logging and acknowledgement behavior.
Configured policies use the native receiver and the retry middleware below.

Projection publishers and workers do not allocate, compare or complete SQL
version tickets. The framework no longer declares a projection-version table.
All index writers must tolerate retries and stale work; a shared consumer queue
does not guarantee SQL commit order across producers.

Publication requires an actual RabbitMQ publisher ACK. Persistent messages use
mandatory routing; an unroutable return is not confirmation. SQL commit timing depends on caller composition;
the publisher neither commits nor inspects the transaction.

Single and batch projections have independent query contracts.
Batch IDs are deduplicated in input order. Empty batches do no I/O; missing
source models raise, without implicitly deleting destination documents.
Conversion completes before any destination write. Methods return `None` on
success and propagate failures. Batch execution uses bulk query hooks.

---

## Other infrastructure

**Redis** — inject `RedisClient` and use `.client` for the full async Redis API
(cache, locks, counters). Responses are decoded to `str`.

**Excel** — `ExcelReader` / `ExcelWriter` run openpyxl on a `ProcessPool`, because
parsing or generating a workbook is blocking CPU work that must never touch the event
loop. Rows are typed: declare an `ExcelRow` and columns map by field order.

```python
from fastamu.infra.excel.row import ExcelRow, Row


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

**Outbound HTTP** — `HTTPConnection` is one pooled `httpx.AsyncClient` for the whole
process, injected like any other infra. A gateway that builds its own client per
call re-runs DNS and the TLS handshake every time and leaks sockets on the way out,
which is how a third-party API that was fine in development starts timing out under
load. Both timeouts come from `http` in `config.yml` — `connect_timeout` separately
from the total, because a dead host holding a task before it is even talking is the
failure a total timeout notices far too late.

Scaffold with `--http` to get an `infra/gateways.py` with a `BaseGateway` subclass
ready to fill in:

```python
class RatesGateway(BaseGateway):
    __base_url__ = "https://api.example.com/v1"
    default_timeout = 5.0          # this API only; otherwise the config default

    async def rate(self, symbol: str) -> Rate:
        resp = await self.get("/rates", params={"symbol": symbol})
        resp.raise_for_status()
        return Rate(**resp.json())          # ← map before it crosses into app/
```

The base owns the base url (an absolute path is left alone, so an API that hands
back full `next` links keeps working), the header layering, and the timeout. It does
not own what a response *means*: map it into **your** domain types in the gateway, so
nothing above `infra/` ends up parsing a third party's JSON shape.

### Security helpers

[fastamu/common/security/tokens.py](fastamu/common/security/tokens.py) and
[fastamu/common/security/crypto.py](fastamu/common/security/crypto.py) are
**config-agnostic on purpose**: the caller passes the secret, the algorithm and the
expiry (wire them from `JWTConfig` / `CryptoConfig`). That keeps `common` free of a
`core.config` import and leaves both files unit-testable without a `config.yml`.

**`security.tokens`** — `create_access_token` / `create_refresh_token` / `decode_token`.
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

**`security.passwords` and `security.crypto`** — three jobs that are easy to
confuse and must not be, so they sit in two files rather than one:

| For | Use | Why that one |
|---|---|---|
| Passwords | `passwords.hash_password` / `verify_password`, or the injectable `PasswordHasher` | bcrypt, deliberately slow. The configured salt is applied as an HMAC **pepper**, which also pre-hashes the input and so sidesteps bcrypt's silent 72-byte truncation. `PasswordHasher` runs both on a worker thread, because "slow" on the event loop means *stopped* |
| Payloads you must read back | `crypto.encrypt` / `decrypt` | Fernet — authenticated, so a tampered ciphertext raises instead of decrypting to garbage. Any passphrase is stretched to a valid key |
| Opaque tokens (refresh tokens, API keys) | `crypto.hash_sha256` + `secure_compare` | Fast and deterministic, so it can be indexed; compared in constant time, so the check leaks no prefix |

A malformed stored hash is a non-match, never an exception — a legacy row cannot take
a login endpoint down.

**`IDEncryption`** ([fastamu/common/security/ids.py](fastamu/common/security/ids.py))
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

`utils.dates` (timezone-aware UTC helpers plus Jalali conversion), `utils.persian`
(digit normalisation, rial/toman formatting), `utils.currency` (parses a quoted
amount — Persian digits, separators, float or `Decimal` — into a storable integer or
exact `Decimal`, and raises on anything that is not a number instead of quietly
returning `0`), `utils.strings`.

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

The URL comes from `db.dsn` in `config.yml` unless it was set
programmatically (which is how the test suite points it at `test_dsn`). Leave the
placeholder `sqlalchemy.url` in `alembic.ini` alone — it is the sentinel that tells
`env.py` to fall back to the config file.

> The template ships with **no revisions** in `migrations/versions/`. Your first
> `--autogenerate` creates the baseline for whatever modules you have.

---

## Testing

`pytest.ini` sets `asyncio_mode = auto` — every `async def` test just runs, no
marker needed. Tests are auto-marked by folder: `tests/unit` → `unit`,
`tests/integration` → `integration`, `tests/api` → `api`.

```bash
pytest                      # everything
pytest -m unit              # fast, no external services
pytest -m integration       # against the real test database
pytest -m api               # drives the live ASGI app
```

The fixtures arrive **with the package**: `fastamu.testing.fixtures` is registered
as a pytest plugin, so a generated project has them with no conftest to copy and
nothing to keep in step. Fastamu's own `tests/conftest.py` is empty for that reason
— its suite runs on the same plugin yours does.

| Fixture | Gives you |
|---|---|
| `migrated_test_db` (session) | Drops and recreates the `public` schema of `db.test_dsn`, then runs `alembic upgrade head`. **Refuses to run against a database whose name lacks `test`.** Skips cleanly if the DB is unreachable — but a migration that fails *after* connecting is still reported as a failure. |
| `pg` | A `DBConnection` on the test DSN |
| `uow` | An open `DBUnitOfWork`; use `transaction()` for writes that must commit |
| `clean_db` | Empties every discovered table **and read-model index** between tests |
| `es` | An `ESClient` on the configured hosts |
| `dishka_container` / `dishka_request` | The **real** DI container, with module providers auto-discovered exactly as in production, but pointed at the test DB and a hermetic schedule source that never touches Redis |
| `anonymous` (in `tests/api`) | An `AsyncClient` over the live app — bootstrapped routers, the framework's error handlers, the same container — with no credentials |

`test_settings_of()` and `core_provider_of()` are plain functions, not fixtures, so
a suite can build its own container from the same wiring — that is how
[tests/api/conftest.py](tests/api/conftest.py) mounts the app. Test settings turn
rate limiting **off**: a suite hits a route far faster than any real client, and a
test failing on a budget it never meant to exercise teaches nothing. A test *about*
limiting turns it back on for itself, since the guards read whichever settings their
own container holds.

Because the container discovers providers through the same bootstrapper, a new
module is testable through DI with **no edit to `conftest.py`** — and for the same
reason `clean_db` empties your new module's table and read-model index without being
told about either. That second half matters: a projected document outlives the row
it came from, so clearing only Postgres would leave a stale document to answer the
next test's search.

---

## Configuration reference

`config.yml` (written by `fastamu new`, and gitignored — it holds your secrets).
The scaffold writes only the optional sections selected at project creation.

| Section | Keys |
|---|---|
| `app` | `modules` — packages the bootstrapper scans; `features` — enabled optional backends; `settings` — optional dotted path to an application `Settings` subclass |
| `fastapi` | `title`, `description`, `version` |
| `db` | `dsn`, `test_dsn`, `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` |
| `tasks.events` | `broker`, `url`, `exchange` — optional FastStream events |
| `tasks.projection` | `broker`, `url`, `prefetch` — optional CQRS projections; requires `es` |
| `tasks.schedulers` | `broker`, `url`, `max_connection_pool_size`, `result_ex_time` — optional Taskiq jobs and cron |
| `redis` | `url`, `max_connections`, `socket_timeout`, `socket_connect_timeout`, `health_check_interval` |
| `rate_limit` | `enabled`, `trusted_proxies`, `general` (`limit`, `window_seconds`), `rules` (name → rule) |
| `es` | `hosts`, `username`, `password`, `api_key`, `verify_certs`, `ca_certs` |
| `http` | `max_connections`, `max_keepalive_connections`, `keepalive_expiry`, `timeout`, `connect_timeout`, `follow_redirects` |
| `jwt` | `algorithm`, `secret_key`, `access_token_expire_minutes`, `refresh_token_expire_minutes`, `api_secret` |
| `crypto` | `encryption_key`, `password_salt` |
| `storage` | `path`, `temp_dir`, `max_file_size`, `allowed_extensions` |
| `csrf` | `secret_key` |
| `logging` | `level`, `format` (`console` \| `json`), `service`, `index` |

---

## Reference modules

The `ops` group ships as **living documentation** — real, working modules that
demonstrate the conventions. Read them, then delete or keep them as you see fit.

- **`ops/storage`** — the most complete example: streamed file upload with
  content-hash dedupe, a paged listing, and a public download route. Shows a mixed
  router (per-route guards with one unauthenticated route), a settings sub-section
  re-provided as its own injectable type, `PagedType` + `PagerMeta`, and a
  module-scoped `resources.py`.
- **`ops/messages`** — pending SMS records, provider gateways, delivery results
  and encrypted public IDs. Automatic background dispatch is unavailable while
  events are being rewritten; the sender service remains callable explicitly.

  ```
  PUT   /messages/providers          register a provider + credentials (upsert by code)
  PATCH /messages/providers/active   switch the provider in use
  PUT   /messages/patterns           map a key (otp) to the provider's template
  POST  /messages                    queue one — answers before anything is sent
  GET   /messages?status=failed      the log, paged
  POST  /messages/{id}/retry         owe a failed one again
  ```

  Out of the box the `console` provider "delivers" to the log, when the sender service
  is called explicitly. The three real gateways (Kavenegar, Melipayamak,
  SMS.ir) need `sms-providers-sdk`, which is imported at call time and installed
  separately:
  `pip install "git+https://github.com/stupidprogrammer4/sms-providers-sdk.git@master"`.
- **`ops/jobs`** — inspecting in-flight taskiq jobs.
- **`ops/system`** — health/info endpoints; the smallest possible module.

---

## House rules

These are the conventions the framework and the codebase assume. Breaking them
usually means something silently stops being discovered.

1. **Absolute imports from `fastamu...` and your own app package** — always.
2. **Every `__init__.py` is empty.** Import from the specific file, never from a
   package root. The bootstrapper relies on this for `routers/` and `tasks/`.
3. **Modules talk through `I*Service` Protocols, never by importing each other.**
4. **A repository holds one statement per method.** All branching, all rules, all
   guards belong in the service.
5. **Input DTOs are `BaseDTO`** (pure pydantic). A repository accepts a model or a
   column dict — never a DTO.
6. **`domain/` imports nothing from `infra/`.** A model declares fields; the table
   that stores them is `infra/tables.py`'s business, and only a repository names
   it.
7. **What crosses a module boundary belongs to that module's domain** (its model,
   its `*Out`, its dataclass) — never another module's type.
8. **Raise typed exceptions; never return an error shape.** The handlers own
   serialisation.
9. **Mark writing application methods `@transactional`.** Its outermost call owns
   commit/rollback; request scope owns only the session lifetime.
10. **New feature = new module.** If you find yourself editing framework code under
   `fastamu/core` or `fastamu/web` to add a feature, stop and reconsider.
11. **Type parameters are declared inline** — `class Repo[T: BaseModel]`, not a
    module-level `TypeVar` plus `Generic[T]`. The bound belongs at the class that
    enforces it.
12. **The line is 79 columns.** `ruff check` and `ruff format` are the arbiters
    (config in `pyproject.toml`); the scaffolder's output already satisfies both.

---

## License

MIT.

Event router discovery only returns routers; the event consumer application
includes them before startup. Keep package
`__init__.py` files empty and declare routers in the leaf Python files.

## Database dialects

Configure the connection under `db` (renamed from `postgresql`). SQLAlchemy
selects the async driver from the DSN; do not maintain a second dialect setting.
The framework adapters cover PostgreSQL, MySQL, MariaDB, SQLite, SQL Server,
and Oracle. Third-party SQLAlchemy dialects need their own adapter registered
in `fastamu.infra.db.dialects.DIALECTS`.

| Family | DSN example | Repository behavior |
| --- | --- | --- |
| PostgreSQL | `postgresql+asyncpg://...` | RETURNING, ON CONFLICT, VALUES bulk updates |
| MySQL / MariaDB | `mysql+asyncmy://...` | Transactional readback, ON DUPLICATE KEY UPDATE, CASE bulk updates |
| SQLite 3.35+ | `sqlite+aiosqlite:///app.db` | RETURNING, ON CONFLICT, CASE bulk updates |
| SQL Server | `mssql+aioodbc://...` | Transactional readback and CASE bulk updates; atomic upsert not implemented |
| Oracle | `oracle+oracledb://...` | Transactional readback and CASE bulk updates; atomic upsert not implemented |

Install the corresponding extras: `fastamu[mysql]`, `fastamu[sqlite]`,
`fastamu[mssql]`, or `fastamu[oracle]`. Vendor client requirements still apply.
SQL Server and Oracle upsert raise `NotImplementedError` before performing I/O.
MariaDB currently uses the conservative MySQL execution path. MySQL upsert can
match any unique index, unlike PostgreSQL's explicit conflict target; callers
must supply keys that identify the resulting row consistently.

`JSONField` is portable: JSONB on PostgreSQL, native JSON where supported, and
serialized text on Oracle. PostgreSQL-only `JSONBField` and `ArrayField` live
in `fastamu.infra.db.dialects.postgresql`. IDs use SQLAlchemy Identity (ignored
where the backend provides its own mechanism) and SQLite's INTEGER variant.
Existing PostgreSQL databases continue to use their existing sequences; review
Identity-related Alembic differences when generating future migrations.

Use `upsert_rows` and `bulk_update_rows` when results are required across
backends. Statement-only `_upsert_stmt` and `_bulk_update_stmt` require a
RETURNING-capable adapter. `_values_grid` is PostgreSQL-specific. On databases
without RETURNING, bulk creates use ORM flush to obtain generated IDs and a
bulk readback; the driver may issue multiple INSERTs. No consecutive-ID
assumption is made. Bulk result order is not guaranteed.

Runtime CRUD, bulk update, upsert, JSON, conflict handling and rollback tests
cover PostgreSQL, MySQL and SQLite. SQL Server and Oracle currently have SQL
compilation checks; MariaDB has native-upsert compilation checks. Live testing
is still required before deploying those three backends. Test cleanup on
non-PostgreSQL databases deletes rows in dependency order without resetting IDs.
