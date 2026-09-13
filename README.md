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

The previous event/projection, outbox/inbox and custom retry implementation
has been removed for redesign. The new projection runtime is available below;
the removed event and outbox/inbox APIs remain unavailable. See
[the design](MESSAGING_REDESIGN.md). SQL transactions, DB/ES
repositories and Taskiq jobs/scheduling remain available. Projection retry is
optional and uses Taskiq's native SmartRetry with a Redis scheduler.

The shared `Register` in `tasks/projection/delivery` maps projection classes to native
Taskiq tasks. `AbstractConvertor`, discovery, registration, publication decorators,
the independent worker and optional retry are implemented. Optional SQL failure storage and periodic batch repair are also implemented. Repair will supply IDs to existing batch
projections; it does not require a special projection class or decorator.
Publication decorators run after successful function completion; transaction
boundaries remain the caller's responsibility.

`fastamu new shop --cqrs --scheduler` enables the ES read side and Taskiq/Redis
jobs. With no flags, neither subsystem is enabled. Pending SMS records are not
automatically dispatched.

## The stack: what each tool does

Fastamu is deliberately not a from-scratch framework. Each concern is delegated
to a mature library; Fastamu's value is the **integration layer** that makes them
behave as one thing.

| Concern | Tool | What Fastamu adds on top |
|---|---|---|
| HTTP, validation, OpenAPI | **FastAPI** | Auto-included routers, a uniform response envelope, typed error handlers, offline (CDN-free) Swagger UI |
| Dependency injection | **dishka** | A `CoreProvider` with the whole infra layer pre-wired; per-module providers discovered and merged automatically; `APP`/`REQUEST` scopes shared identically by the web app *and* the task worker |
| Scheduled jobs & cron | **taskiq** (Redis streams) | A broker that boots the same DI container as the web app, per-module task auto-registration, logging middleware |
| Write side / ORM | **SQLModel** + **SQLAlchemy 2.0** (async) | Explicit repositories for each database and entity shape, native writes, paging/streaming helpers, and a request-scoped `UnitOfWork` |
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
fastamu new shop --scheduler && cd shop

# 2) Config — config.yml is gitignored; it holds your secrets
#    fill in: db.dsn, db.test_dsn, redis.url,
#             tasks.schedulers.url, jwt.secret_key, crypto.encryption_key
pip install -e ".[dev]"

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

Working *on* Fastamu itself instead? Clone it and `pip install -e ".[dev,scheduler]"` —
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
├── messaging/       # Messaging contracts and optional capabilities
│   └── projections/
│       ├── contracts/ # What an application implements: single, batch, fanout,
│       │              # patch, delete, policy, results
│       └── repair/    # Optional recovery: the failure queue contract, the
│                      # Redis list behind it, and what reruns a failure
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
│   ├── db/          # repository contracts/tools, typed connections and UoWs
│   ├── es/          # client, repository, analyzers
│   ├── redis/       # pooled async client
│   ├── http/        # pooled httpx client + BaseGateway
│   └── excel/       # ProcessPool-backed reader / writer
│
├── tasks/           # Background job execution
│   ├── schedulers/  # Redis jobs, cron and middleware
│   └── projection/  # broker.py and scheduler.py are entry points;
│                    # delivery/ registers and publishes, repair/ reruns
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
│   ├── tables.py       # the SQLModel tables carrying domain/entities.py
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

The reader extends `PostgreSQLReader` — a repository base
with no model or table bound to it. It receives its typed UoW and session and
returns the context its logic needs. The service splits in
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
| **Tables** | `<module>/infra/tables.py` | Imported so the `table=True` classes register on the shared metadata (this is what Alembic autogenerate sees). Only this file — a `domain/entities.py` maps to nothing |
| **ES documents** | `<module>/domain/documents.py` | Every `AsyncDocument` subclass; its index is created on app startup if missing |
| **Schedulers** | `<module>/tasks/schedulers/*.py` | Imported by `boot_schedulers()` to register Taskiq jobs |

Consequences worth internalising:

- **`routers/` and `tasks/` are packages whose `__init__.py` stays empty.** The
  bootstrapper imports each *file* inside them. Re-exporting from `__init__.py`
  is not just unnecessary, it is against the convention.
- **`providers.py`, `domain/entities.py` and `infra/tables.py` are single files**, not packages.
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
fastamu module catalog.product --tasks       # Taskiq jobs
fastamu module catalog.product --scheduler   # only tasks/schedulers/
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

### 1. The model — `domain/entities.py`

A model declares **fields and nothing else**. It is not the table: no `table=True`,
no ORM base, no `__tablename__`. That is what keeps `domain/` honest — it names
what a brand *is*, and knows nothing about where brands are kept.

```python
from fastamu.common.models.entities import PersistenceEntity
from fastamu.common.models.fields import BoolField, CharField


class BrandModel(PersistenceEntity):
    name: str = CharField(35, index=True)
    slug: str = CharField(55, unique=True)
    is_active: bool = BoolField(default=True)
```

`PersistenceEntity` contributes `id`, `created_at` and `updated_at`. Columns use
the **field factories** from
[fastamu/common/models/fields.py](fastamu/common/models/fields.py), which default to
`NOT NULL`. Common options are direct named arguments:

```python
name: str = CharField(100, unique=True, db_column="display_name")
metadata: dict = JSONField(default_factory=dict)
note: str | None = TextField(default=None, nullable=True)
```

`default` and `default_factory` declare model defaults. `nullable` and
`server_default` do not implicitly add a model default. A callable factory is
passed as `default_factory`, never inferred from `default`. Strings supplied
as `server_default` remain literal strings; pass `text(...)` or a SQLAlchemy
expression when SQL should run. For example, use `server_default="pending"`
for a string and `server_default=func.current_timestamp()` for a timestamp.
`db_column` renames the physical column without changing the model field.
`onupdate`, `server_onupdate`, `index`, `unique` and `comment` are also direct
options. Advanced SQLAlchemy column options can use `sa_column_kwargs`.
The helpers neither inspect nor modify the supplied options per query.

`JSONField(none_as_null=False)` stores Python `None` as JSON `null`;
`none_as_null=True` selects SQL `NULL`. MySQL ORM inserts follow SQLAlchemy's
native omission rules for scalar columns with defaults; use an explicit SQL
`null()` in a custom statement when required. Repositories never rewrite None.
`VersionField` stores a version number; choose its default and update
expression explicitly. `VersionEntity` starts at database version 1 and does
not install an implicit increment.

Bases: `BaseEntity` (bare), `IdentifiedEntity`, `TimestampEntity`,
`PersistenceEntity`.

Field factories: `IDField`, `SmallIntField`, `IntField`, `BigIntField`, `BoolField`,
`FloatField`, `NumericField`, `CharField`, `TextField`, `DateField`,
`TimestampField` (timezone-aware), `JSONBField`, `ArrayField` (optional GIN index),
`EnumField` (native PG enum), `ComputedField` (generated column), `ForeignKeyField`.

### 1b. The table — `infra/tables.py`

One line maps the model onto a real table. This file is the *only* place that
knows a database exists, and the only one the bootstrapper imports for metadata:

```python
from fastamu.infra.db.table import BaseTable
from shop.modules.catalog.brands.domain.entities import BrandModel


class BrandTable(BrandModel, BaseTable, table=True):
    pass
```

Constraints and indexes that span columns live here too — `__table_args__`, a
`UniqueConstraint`, an explicit `__tablename__`. Repositories are still declared
against the **model** (`PostgreSQLIdentifiedRepository[BrandModel]`) and bind
`table = BrandTable` explicitly in `infra/`.

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
from shop.modules.catalog.brands.domain.entities import BrandModel


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
from fastamu.infra.db.repositories.backends.postgresql import PostgreSQLIdentifiedRepository
from fastamu.infra.db.tools.read import fetch_page
from fastamu.modules.catalog.brands.domain.entities import BrandModel
from fastamu.modules.catalog.brands.infra.tables import BrandTable


class BrandRepository(PostgreSQLIdentifiedRepository[BrandModel]):
    table = BrandTable

    async def get_by_slug(self, slug: str) -> BrandModel | None:
        stmt = select(BrandModel).where(col(BrandModel.slug) == slug)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(self, page: int, per_page: int) -> PagedType[BrandModel]:
        stmt = select(self.table).order_by(col(self.table.id).desc())
        return await fetch_page(self.uow, stmt, offset=(page - 1) * per_page, limit=per_page)
```

`fetch_page` returns the page **and** the total match count. The count is its own
statement (the filters wrapped in a subquery, ordering dropped), which costs a
round-trip and buys a paginator that behaves the same whatever select you hand it —
a window function riding along on the page would have to be added to your statement,
breaking `scalars()` and mis-counting anything that is not a plain `select(Model)`.

### 5. Logic — `app/services.py`

Business rules live here, and only here. `BaseIDService` reads the model off the
generic parameter and gives you guards that raise the framework's typed errors.

```python
from fastamu.common.services import BaseIDService
from fastamu.infra.db.tools.decorators import transactional
from fastamu.common.errors.exceptions import ConflictException
from fastamu.core import resources
from fastamu.modules.catalog.brands.domain.dtos import BrandCreate, BrandUpdate
from fastamu.modules.catalog.brands.domain.entities import BrandModel
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
        record = self._check_for_id_existence(id, await self.repo.get_by_id(id))
        await self.repo.remove_by_id(id)
        return record
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
from fastamu.modules.catalog.brands.domain.entities import BrandModel


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
class. `BrandRepository`'s `PostgreSQLUnitOfWork` argument is resolved by `CoreProvider`
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
| `DBConnection[PostgreSQLUnitOfWork]` | APP | The default async engine + session factory |
| `PostgreSQLUnitOfWork` | **REQUEST** | An open PostgreSQL session; operations own commit/rollback |
| `ESClient` | APP | Async Elasticsearch client |
| `RedisClient` | APP | Pooled async Redis client |
| `ScheduleSource` | APP | The taskiq Redis schedule source (for scheduling jobs at runtime) |

**The transaction boundary is an application operation.** Dishka opens a
backend-specific UoW when it is first resolved and closes it at scope exit. Scope exit
never commits. SQLAlchemy discards any outstanding transaction when the session
closes. Repositories execute SQL through `uow.execute()`; they do not own the transaction.

Use `@transactional` on a writing application method. It requires an open UoW,
commits before returning, and rolls back on an exception or cancellation before
commit. Nested decorated calls join the outer operation; only its owner commits.
A failed nested operation marks the outer transaction rollback-only even if its
exception is caught. Do not manually commit/rollback inside this boundary.
Use `unit.savepoint()` to isolate a SQL failure and catch it outside the
savepoint scope. A decorated operation cannot start inside a savepoint.
Concurrent operations need separate UoWs; a child task cannot
borrow an inherited application transaction.

```python
from fastamu.infra.db.tools.decorators import transactional
from fastamu.infra.db.transaction import transaction

@transactional
async def rename_product(repo, product_id, title):
    return await repo.update_by_id(product_id, {"title": title})

# Outside Dishka, open a session and use an explicit operation boundary:
async with database.uow() as unit:
    async with unit.transaction():
        await unit.execute(statement)
```

The UoW tools are explicit:

| Tool | Behavior |
|---|---|
| `open()` / `close()` | Own the session lifetime; also used by `async with` |
| `transaction()` | Commit on success, roll back on failure; select this UoW explicitly |
| `commit()` / `rollback()` | Manually manage a transaction boundary |
| `flush()` | Send pending ORM changes without committing |
| `refresh(instance, attributes=...)` | Explicitly reload an object or chosen fields |
| `savepoint()` | SQLAlchemy nested transaction; entering flushes pending ORM changes |
| `is_open` / `in_transaction` | Inspect session lifetime / active SQL transaction state |
| `now()` | Read the database timestamp |
| `execute(stmt, params, ...)` | Return the buffered SQLAlchemy `Result`, preserving its row types |
| `stream(stmt, params, ...)` | Return a raw `AsyncResult`; the caller closes the cursor |
| `session` | Access SQLAlchemy directly, including ORM `add` / `add_all` |

`open()` replaces the old session-opening `begin()` method, with no deprecated
alias. Closing permanently closes that session; reopening a UoW creates a new
one. Repositories from an expired scope cannot silently reuse its session.
Cancellation during close is propagated after session cleanup finishes,
including when the caller is cancelled repeatedly.
When several databases are open, use `unit.transaction()` or
`transaction(unit)` to choose the boundary explicitly. Each repository uses
the UoW injected into it; selecting a transaction does not redirect repositories.

The UoW has no message callbacks, version allocation or broker operations.
HTTP error handlers only format errors; they never resolve a database session
or perform rollback. This also covers errors translated into HTTP responses:
uncommitted work is discarded at session close.

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

In `fastamu.common.models.entities` — all pure, none of them a table:

| Base | Adds |
|---|---|
| `Base` | `to_row()`, `to_dict()`, `to_json()`, `patch()`, `from_obj()`, `from_objs()`, … |
| `BaseModel` | nothing — the plain entity base |
| `IdentifiedEntity` | `id` |
| `TimestampEntity` | `created_at`, `updated_at` (DB-managed) |
| `PersistenceEntity` | all of the above — the usual choice |

`BaseTable`, in `fastamu.infra.db.table`, is what turns one into a
table, and it is the only base that carries a `__tablename__`.

### Explicit repositories

Choose both the database and the entity shape. Declare the table directly;
there is no repository factory, table discovery or runtime generic inspection.

```python
from fastamu.infra.db.repositories.backends.postgresql import (
    PostgreSQLPersistenceRepository,
)
from shop.modules.catalog.products.domain.entities import ProductEntity
from shop.modules.catalog.products.infra.tables import ProductTable


class ProductRepository(PostgreSQLPersistenceRepository[ProductEntity]):
    table = ProductTable
```

Each database provides four entity repository shapes and a reader.
Replace `PostgreSQL` with `MySQL`,
`MariaDB`, `SQLite`, `MSSQL` or `Oracle` and import from its corresponding file
under `fastamu.infra.db.repositories.backends`.

| Shape | Example | Methods |
|---|---|---|
| Reader | `PostgreSQLReader` | Typed UoW for custom joins, aggregates and reports; no bound table |
| Base | `PostgreSQLRepository[T]` | Explicit-column SQL builders; create/upsert/bulk writes; `get_one`, `get_all`, `get_all_stream`, `exists`, `count`, `get_page`, conditional `update` and `remove` |
| ID | `PostgreSQLIdentifiedRepository[T]` | Base methods plus `get_by_id`, `get_by_ids`, `get_paged`, `update_by_id`, `update_by_ids`, `update_row_by_id`, `remove_by_id`, `remove_by_ids` |
| Timestamp | `PostgreSQLTimestampRepository[T]` | Base methods plus `get_stream_range`, `get_paged_range` and `gt`, `ge`, `lt`, `le` stream/page variants |
| ID + timestamp | `PostgreSQLPersistenceRepository[T]` | Combines the ID and timestamp methods |

Reusable database tools live together, separate from session and transaction ownership:

```text
db/
├── connection.py
├── uow.py
├── transaction.py       # transaction scope and ownership
├── tools/
│   ├── read.py          # scalar/model pagination and streaming
│   └── decorators.py    # @transactional
├── dialects/            # backend behavior, SQL types and database-specific tools
└── repositories/
```

Import `transactional` from `fastamu.infra.db.tools.decorators`, reading helpers
from `fastamu.infra.db.tools.read`. Database-specific helpers stay in
`dialects`: PostgreSQL fields, `reset_schema` and `truncate_tables` are in
`fastamu.infra.db.dialects.postgresql`.

Repositories are separated into declarations and executable tools:

```text
repositories/
├── contracts/
│   ├── base.py         # common abstract obligations and reader contract
│   ├── postgresql.py   # PostgreSQL contracts for all four shapes
│   └── ...             # one contract module per database
└── backends/
    ├── postgresql.py   # native PostgreSQL statements and execution
    └── ...             # one implementation module per database
```

Each implementation inherits its database's abstract contract. Incomplete
implementations cannot be instantiated. `contracts/base.py` declares only
shared operations; database contracts specify their native write results and
supported tools. For example, MySQL/MariaDB ID updates return `int`, while
PostgreSQL ID updates return models. Oracle/MSSQL contracts expose no upsert.
All six databases have Base, Identified, Timestamp and Persistence contracts.

Database families share no executable repository base. Their constructors take
backend-specific UoWs: `PostgreSQLRepository` takes `PostgreSQLUnitOfWork`,
`MySQLRepository` takes `MySQLUnitOfWork`, and likewise for the other backends.
A single `DBConnection[U]` takes `uow_factory` and creates that UoW type.
There is no repository
`validate()` or custom binding registry. Static type checking rejects the wrong
UoW argument; Dishka rejects a missing typed dependency when building the
container. A DSN is configuration data, so its correctness is checked by the
database driver when connecting.

Application providers use native Dishka registration:

```python
from dishka import Provider, Scope, provide
from fastamu.infra.db.repositories.contracts.postgresql import (
    PostgreSQLPersistenceRepositoryContract,
)

class CatalogProvider(Provider):
    products = provide(
        ProductRepository,
        provides=PostgreSQLPersistenceRepositoryContract[ProductEntity],
        scope=Scope.REQUEST,
    )
```

`CoreProvider` configures the default connection explicitly:

```python
connection = DBConnection(
    dsn=settings.db.dsn,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
    pool_timeout=settings.db.pool_timeout,
    pool_recycle=settings.db.pool_recycle,
    uow_factory=PostgreSQLUnitOfWork,
)
# Inferred type: DBConnection[PostgreSQLUnitOfWork]
# connection.uow() returns PostgreSQLUnitOfWork.
```

For another backend, pass its UoW class as the factory and register it in the
application's ordinary Dishka provider. There are no per-database connection
classes or framework database providers. The provider opens the unit directly:

```python
@provide(scope=Scope.REQUEST)
async def uow(
    self, connection: DBConnection[PostgreSQLUnitOfWork]
) -> AsyncIterator[PostgreSQLUnitOfWork]:
    async with connection.uow() as unit:
        yield unit
```

For several connections of the same type, register their connection, UoW and
repositories in matching Dishka components. The factory is chosen explicitly
at configuration time; no backend discovery occurs in repository operations.

The example modules and scaffold explicitly choose PostgreSQL. Changing the
DSN does not change their repository or dependency types.

```python
# database is a DBConnection[PostgreSQLUnitOfWork].
async with database.uow() as uow:
    repo = ProductRepository(uow)
    async with uow.transaction():
        product = await repo.create(ProductEntity(name="Example"))
        product = await repo.update_by_id(product.id, {"name": "Updated"})
```

Writes never commit implicitly. MySQL `create`/`bulk_create` use ORM `add`,
`flush` and `refresh`; native returning implementations use SQLAlchemy DML with
`RETURNING` or the database equivalent. MySQL/MariaDB update methods execute
only UPDATE and return the affected-row count. PostgreSQL, SQLite, Oracle and
MSSQL return rows from the write statement.
Update methods never issue a SELECT; callers read explicitly when needed.
Bulk updates join a typed input relation: PostgreSQL and MSSQL use VALUES,
SQLite uses a VALUES CTE, and MySQL/MariaDB use a UNION ALL derived table.
Oracle uses a correlated multi-column assignment from a UNION ALL input
relation, retaining native RETURNING without requiring UPDATE FROM.
Each backend exposes `_values_grid(rows, *, columns, name="incoming")` for
custom queries. PostgreSQL takes its existing sequence of SQL columns; the
other backends take an explicit input-name-to-column mapping. No builder
discovers fields or executes SQL.

MySQL also provides `bulk_insert(data, *, insert_columns) -> int` for a native
batch INSERT without loading or refreshing ORM objects. `insert_columns` maps
input field names to SQL columns, just as for `bulk_upsert`; every selected
field must be supplied in every row. The result is the driver's affected-row
count (zero for empty input). Failed inserts raise; the caller owns rollback.
`_bulk_insert_stmt(rows, *, insert_columns)` exposes the same native SQL builder.
The existing `bulk_create` continues to return fully refreshed models.

```python
columns = ProductTable.__table__.c
count = await repo.bulk_insert(
    products,
    insert_columns={"name": columns.name, "price": columns.price},
)
```

`remove_by_id(s)` returns the driver's affected-row count; it does not read
deleted records. Obtain a record explicitly first
when its contents are needed after deletion.

`update_by_id(s)` accepts a field mapping. An omitted field stays untouched;
explicit `None` follows the column's SQLAlchemy type semantics. Callers supply
a nonempty change mapping without primary-key changes. `update_row_by_id`
accepts a partial entity; its `id` argument identifies the target row.
`bulk_update` accepts a nonempty batch with distinct IDs, at least one change field, and the
values for every explicitly selected update field. SQLite, MySQL, MariaDB,
Oracle and MSSQL take `update_columns={"field_name": column}`. PostgreSQL
accepts raw row mappings and its own explicit match/update columns. Callers
validate their inputs before calling the repository; it performs no batch validation or fallback reads.
Returned rows from bulk writes are not guaranteed to match input order;
use their IDs. Timestamp
ranges use `created_at`, inclusive endpoints, and UTC datetimes. Persistence
pages use `(created_at, id)` ordering; timestamp-only repositories order by
`created_at` and applications can override `_time_query` to break ties with
their own key.

### PostgreSQL tools and prepared operations

PostgreSQL builders live on `PostgreSQLRepository[T: BaseEntity]` and have no
ID convention. They accept row mappings and explicit SQLAlchemy columns
(`Table.__table__.c`), rather than deriving columns from an entity or the first
row. All four builders perform no I/O and leave RETURNING and execution
options to the caller:

| Builder | Explicit inputs | Result |
|---|---|---|
| `_values_grid(rows, *, columns, name="incoming")` | Ordered columns and their SQL types | `Values`, usable in joins and CTEs |
| `_upsert_stmt(row, *, conflict_columns, update_columns, changes=None)` | Conflict keys, fields copied from `excluded`, optional column-to-expression assignments | PostgreSQL `Insert` |
| `_bulk_upsert_stmt(rows, *, insert_columns, conflict_columns, update_columns, changes=None)` | Exact insertion columns and native conflict/update expressions | PostgreSQL `Insert` |
| `_bulk_update_stmt(rows, *, key_columns, update_columns)` | Match keys (including composite keys) and fields copied from the grid | `Update` |

Upsert input mappings use model/data field names. `insert_columns` maps each
input field name to its SQLAlchemy column. PostgreSQL VALUES and bulk-update
row mappings use the supplied column keys. Batches must be nonempty; the caller supplies
valid conflict/match keys and the required row values. Batch update keys must
be unique and disjoint from update columns. An upsert needs at least one update
column or explicit change expression. Builders do not validate application
input, discover fields, exclude `id`, or synthesize fallback updates.

```python
# Inside a custom repository; rows are mappings, not model instances.
columns = ProductTable.__table__.c
stmt = self._bulk_upsert_stmt(
    rows,
    insert_columns={"code": columns.code, "name": columns.name, "price": columns.price},
    conflict_columns=[columns.code],
    update_columns=[columns.name, columns.price],
    changes={columns.version: columns.version + 1},
)
stmt = stmt.returning(columns.id, columns.version)
result = await self.uow.execute(stmt)
return result.all()
```

For ready operations, `upsert(data, ...)` accepts one entity and
`bulk_upsert(items, ...)` accepts a sequence. Both require `conflict_columns`
and `update_columns` and return the model(s) from native RETURNING.
`bulk_upsert` additionally requires an `insert_columns` field-to-column mapping.
Every item must explicitly
supply every selected insertion column; use explicit `None` for SQL NULL where
the column allows it. A missing selected value raises `KeyError` before SQL
execution. Extra fields outside `insert_columns` are deliberately excluded.
For different insertion shapes, the caller submits separate batches. Column
selection never depends on the first item or assumes matching SQL/model names. Single upsert uses `_upsert_stmt`
and bulk upsert uses `_bulk_upsert_stmt`; neither routes through the other.
PostgreSQL `bulk_update(rows, *, key_columns, update_columns)` accepts mappings,
returns updated models, and works without an `id` column. Custom repository
methods choose their columns; services need not know SQLAlchemy tables.

`get_one(*conditions)` raises if several records match. `get_all(*conditions)`,
`exists(*conditions)` and `count(*conditions)` accept SQLAlchemy expressions.
`get_page(order_by=..., limit=..., offset=..., where=...)` requires explicit
ordering. `get_all_stream(batch_size, where=...)` streams filtered models.
`update(where, changes)` returns written models; `remove(where)` returns the
affected-row count. Both require an explicit predicate and execute only a
write statement. ID repositories add convenience operations with fixed ID
predicates; timestamp repositories add their time-range operations.

Repository reads follow normal ORM identity-map behavior and preserve pending
model changes. Query helpers preserve the caller's execution options. For an
explicit refresh, build a select with
`.execution_options(populate_existing=True)` and execute it with the session;
this deliberately replaces the loaded state, including unflushed changes.
Public returning writes populate models from their own write results.
This also replaces unflushed changes on those returned models, just like an
explicit refresh. UPDATE and DELETE disable automatic session synchronization;
they do not issue a SELECT to synchronize other loaded objects.
Count-returning writes do not reload existing ORM objects; call
`await uow.refresh(record)` explicitly when you need their database state.

Every backend's protected `_bulk_update_stmt` returns an `Update` without
RETURNING or execution options. Custom methods choose their own result columns
and session policy. Public `bulk_update` applies the backend's result and
synchronization policy after building the statement, including when a subclass
replaces the builder.

### Other backends and optional upsert

Native upsert tools live on the database repository itself, so all four
entity shapes can use them without an `id` convention. PostgreSQL and SQLite
use `ON CONFLICT`; MySQL and MariaDB use `ON DUPLICATE KEY UPDATE`. Oracle and
MSSQL expose no upsert methods in this API. The shared base contract and
readers do not require or provide upsert.

```python
columns = ProductTable.__table__.c

# SQLite: the caller chooses the conflict target and copied columns.
product = await repo.upsert(
    data,
    conflict_columns=[columns.code],
    update_columns=[columns.name],
)
products = await repo.bulk_upsert(
    items,
    insert_columns={"code": columns.code, "name": columns.name},
    conflict_columns=[columns.code],
    update_columns=[columns.name],
)

# MySQL / MariaDB: conflicts use the database's unique indexes.
result = await repo.upsert(data, update_columns=[columns.name])
results = await repo.bulk_upsert(
    items,
    insert_columns={"code": columns.code, "name": columns.name},
    update_columns=[columns.name],
)
```

Each supported backend supplies independent `_upsert_stmt(row, ...)` and
`_bulk_upsert_stmt(rows, *, insert_columns, ...)` builders. Both return the
native dialect's `Insert` without executing, adding RETURNING, or selecting
execution options. Subclasses can extend the statement before execution.
SQLite and MariaDB public upserts return models from the native write result.
MySQL returns the affected-row count, which is not the number of input items;
read records explicitly when needed. All supported backends accept optional
`changes={column: expression}`; these explicit assignments override copied
update columns. Upsert does not infer `Column.onupdate` values; supply those
explicitly. No primary-key fields are implicitly selected or excluded.

Constraint errors remain SQLAlchemy exceptions. Translate them at the
application boundary if an HTTP/domain error is required; repositories do not
parse driver errors on every write.

### Queries without a table repository

Each database has its own reader: `PostgreSQLReader`,
`MySQLReader`, `MariaDBReader`, `SQLiteReader`,
`OracleReader`, and `MSSQLReader`. Each implements its own
reader contract and takes the matching UoW. These readers can query several
tables. Each contract provides a typed UoW; it requires no `table`,
entity model or predefined query methods. A reader defines its own methods,
constructs its joins/CTEs/aggregates, and maps the full result into its context
or report type.

```python
from sqlalchemy import func, select
from sqlmodel import col
from fastamu.infra.db.repositories.backends.postgresql import (
    PostgreSQLReader,
)

class CatalogReader(PostgreSQLReader):
    async def counts_by_category(self) -> dict[str, int]:
        stmt = (
            select(CategoryTable.name, func.count(ProductTable.id))
            .join(ProductTable, col(ProductTable.category_id) == CategoryTable.id)
            .group_by(CategoryTable.name)
        )
        result = await self.uow.execute(stmt)
        return {name: count for name, count in result}
```

Register the reader with Dishka's ordinary `provide(CatalogReader)`; its
constructor receives `PostgreSQLUnitOfWork`. Choose `result.mappings()` for
named report fields, iterate full rows for joined columns/entities, or use
`result.scalars()` when the query deliberately selects a single value/model.
The base does not collapse results to their first column. `uow.execute()` and
`uow.stream()` forward parameters, execution options and bind arguments to
SQLAlchemy. They do not map results, refresh objects or commit. Result
consumption and conversion belong to the reader or repository.

Standalone `fetch_page(uow, stmt, ...)` and `stream(uow, stmt, ...)`
remain optional helpers for **single-value/model** queries. They are not
requirements of the reader contract. Streaming closes the result when the
generator is closed; use `aclosing` when stopping early.

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

from fastamu.modules.catalog.brands.interfaces import IBrandService
from fastamu.tasks.schedulers.broker import broker


@broker.task(
    task_name="deactivate_stale_brands",
    queue_name="brands_queue",              # optional: give the task its own stream
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
  scope**, so it gets its own typed UoW. Writing application methods use
  `@transactional`, with the same commit/rollback semantics as in HTTP handlers.
- **Enqueue from anywhere** with `await deactivate_stale_brands.kiq(arg)` — including
  from a route handler, since the web app imports the broker too.
- No retry middleware is installed automatically during the messaging redesign.
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
It requires `es` configuration and retains `ESRepository` and index discovery.
Automatic projection delivery and the previous projection base classes have
been removed for redesign; this flag does not start a projection worker.

`AbstractProjection[TModel, TDocument]` runs source lookup, synchronous
conversion and an awaited destination write. IDs are integers; model types
extend Pydantic `BaseModel` and document types extend `AsyncDocument`.

```python
from elasticsearch.dsl import M, AsyncDocument

from fastamu.common.models.entities import IdentifiedEntity
from fastamu.infra.db.repositories.backends.postgresql import PostgreSQLIdentifiedRepository
from fastamu.infra.db.tools.read import fetch_page
from fastamu.infra.es.repository import ESRepository
from fastamu.messaging.projections.contracts.base import AbstractProjection


class Product(IdentifiedEntity):
    title: str


class ProductDocument(AsyncDocument):
    title: M[str]

    class Index:
        name: str = "products"


class ProductProjection(AbstractProjection[Product, ProductDocument]):
    def __init__(
        self,
        products: PostgreSQLIdentifiedRepository[Product],
        search: ESRepository[ProductDocument],
    ) -> None:
        self.products = products
        self.search = search

    async def _db_query(self, id: int) -> Product:
        product = await self.products.get_by_id(id)
        if product is None:
            raise LookupError(f"Product {id} does not exist")
        return product

    def _convert(self, model: Product) -> ProductDocument:
        document = ProductDocument(title=model.title)
        document.meta.id = str(model.id)
        return document

    async def _es_query(self, document: ProductDocument) -> None:
        await self.search.save(document)
```

Call `await projection.project(42)` on the injected or constructed instance.
Lookup must return a model or raise; missing-source handling belongs to the
application. A failed stage stops execution and propagates its error. The base
class does not register tasks, load settings, retry or select a write policy.

The execution shapes are explicit:

| Module under `fastamu.messaging.projections.contracts` | Class | Entry point | Result |
| --- | --- | --- | --- |
| `base` | `AbstractProjection[TModel, TDocument]` | `project(id: int)` | `None` |
| `base` | `AbstractBatchProjection[TModel, TDocument]` | `batch_project(ids: Sequence[int])` | `list[BulkItemResult]` |
| `base` | `AbstractFanoutProjection[TModel, TDocument]` | `project(id: int)` | `list[BulkItemResult]` |
| `patch` | `AbstractPatchProjection[TModel, TPatch]` | `project(id: int)` | `None` |
| `patch` | `AbstractBatchPatchProjection[TModel, TPatch]` | `batch_project(ids: Sequence[int])` | `list[BulkItemResult]` |
| `delete` | `AbstractUnProjection` | `unproject(id: int)` | `None` |
| `delete` | `AbstractBatchUnProjection` | `batch_unproject(ids: Sequence[int])` | `list[BulkItemResult]` |

Batch projections receive IDs from their caller. ID selection, failure-store
queries and scheduling belong to the optional repair task, outside projections.
The previous `SyncProjection`, `get_ids()` contract and `@sync` decorator have
been removed. Send an existing batch task explicitly:

```python
await register.get(RebuildProducts).kiq(ids=[7, 3])
```

For reusable conversion, subclass
`AbstractConvertor[TModel, TDocument]` from
`fastamu.messaging.projections.contracts.convertor` and implement the synchronous
`convert(model: TModel) -> TDocument` method. The projection can receive this
converter through its constructor and call it from `_convert`. Source and
destination types are generic; conversion does not require a broker or settings.

Patch types extend Pydantic `BaseModel`. The single writer receives `(id, patch)`;
the batch lookup returns `Mapping[int, TModel]` keyed by patch target ID and its
writer receives `Mapping[int, TPatch]`. IDs remain associated with their patches
even when a query returns a different order. Serialize supplied fields with
`patch.model_dump(mode="json", exclude_unset=True)` in the writer. Do not use
`exclude_none=True` when an explicit null is a requested change.
[Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/).

Document batches read a `Sequence[TModel]`, convert all models before writing,
then call `_es_query(documents)` once. Fanout uses that same sequence of stages
from one source ID. Deletion calls only `_es_query`, without a lookup or converter.
Empty input batches do no I/O. Empty query results do no destination writes;
the application must raise from lookup if a missing source is an error. The
framework does not infer completeness from row counts, deduplicate IDs, or
implicitly delete documents whose sources are absent.

Bulk writers return one `BulkItemResult` for each destination operation: its
string document `id`, integer HTTP `status`, and optional structured `error`.
Results describe destination writes, not source lookup completeness. They are
returned unchanged, including failures. `succeeded` requires a 2xx status and no
error. Two further outcomes need no repeat and are reported as such: `superseded`
(409) means a newer write already holds the document, and `absent` (404) means
there was nothing to write or to remove. `settled` covers all three, and it — not
`succeeded` — decides whether an item raises `ProjectionBatchError`, is recorded
as a failure, or resolves a claimed repair record.

That distinction is what makes ordering fences usable. Two updates to one ID are
independent messages, so a slower worker can overwrite newer data. Write with
`version_type=external` and a monotonic source column, and Elasticsearch rejects
the older write with 409; because 409 is settled, the rejection is not recorded
as a failure and is not repaired in a loop. An application that instead uses
`if_seq_no`/`if_primary_term` and *wants* a retry must map that conflict to a
retryable status of its own in its bulk writer. Single-document shapes return
`None` and have no per-item channel, so they swallow a conflict or a missing
document inside their own destination write.

An exception before a complete result is available propagates without retry.
[Elasticsearch bulk results](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/docs-bulk.html).

The existing `ESRepository.bulk_*` count-returning methods do not provide this
per-item result contract. A bulk writer can use the native `async_streaming_bulk`
helper with `raise_on_error=False` and `yield_ok=True`, mapping each returned
operation's `_id`, `status` and `error` to `BulkItemResult`. It must preserve
failures, rather than report an aggregate count as full success. No repository
adapter or transport is installed automatically by these classes.

Full-document writers choose create-only or replacement explicitly; patch
writers choose update behavior, including conflicts and upserts. Batch and fanout
results do not raise merely because an item failed. A future task integration
must decide how to handle them before reporting task success. Automatic
registration with native Taskiq tasks is implemented in the projection package.

### Projection discovery and task registration

Declare `queue_name: ClassVar[str]` on each concrete projection. The bootstrapper
discovers classes in `<module>/app/projections.py` or the immediate Python files
of `<module>/app/projections/`, including definitions in its `__init__.py`.
Abstract classes, imported classes and repeated aliases are skipped; nested
subpackages are not scanned. Import errors inside projection modules propagate.

`fastamu.tasks.projection.delivery.register.Register` owns the class-to-task dictionary
and task construction. Its public methods are `register(projection, broker)`
and `get(projection)`. Task construction and Dishka wrappers are protected
methods of the same class; there is one shared `register` instance:

```python
from fastamu.tasks.projection.delivery.register import register

# During startup, with the runtime's native broker and Dishka setup:
for projection_class in bootstrapper.boot_projections():
    register.register(projection_class, broker)

# Once the producer broker has started:
await register.get(ProductProjection).kiq(id=42)
```

The task name is the class's `module:qualname`; `queue_name` is a routing label.
Renaming a class changes its task name. Multiple tasks can share a queue, but
the runtime must also configure those queues on the broker. Each worker attempt
resolves its projection through the current Dishka scope; application providers
must supply the concrete projection and its dependencies. Producer registration
does not instantiate projections. A repeated binding is idempotent; conflicting
class/task bindings or task names raise instead of silently replacing tasks.

The task adapter raises `ProjectionBatchError` if any returned bulk item failed;
its `results` attribute preserves all item outcomes. Direct projection calls
continue to return their results. Retry requires an explicit class policy;
failure storage is enabled separately through the repair configuration.

### Running and publishing projections

Install `fastamu[projection]` and enable the optional backend in `config.yml`:

```yaml
tasks:
  projection:
    url: amqp://guest:guest@localhost:5672/
    exchange: fastamu.projection
    prefetch: 10
```

Each concrete class declares a nonempty `queue_name: ClassVar[str]`. The broker
discovers the classes, declares their durable queues on a direct exchange and
registers their tasks. The native broker's dead-letter queue is named
`<exchange>.dead_letter`; it is not a retry/reconciliation store implemented by
Fastamu. Queue names should belong to this application's projection runtime.

Run the independent worker with the native CLI:

```bash
taskiq worker fastamu.tasks.projection.broker:broker --workers 1 --max-async-tasks 10
```

Prefetch limits unacknowledged deliveries; `--max-async-tasks` controls worker
concurrency. The worker creates its own Dishka container and DB/ES resources.
It closes the container on shutdown, including disposal of its DB pool.
Producer startup registers tasks without creating the worker's container.
The web application's `task_lifespan()` starts the configured producer broker;
scripts can use that same context manager explicitly.

Publication decorators live with the Taskiq adapter:

```python
from fastamu.infra.db.tools.decorators import transactional
from fastamu.tasks.projection.delivery.decorators import project

class ProductCommands:
    @project(ProductProjection, lambda result: result.id)
    @transactional
    async def update(self, command: UpdateProduct) -> Product:
        return await self.products.update(command)
```

`project`, `patch`, `unproject` and `fanout` accept a mapper returning one integer
ID. They share the same publication behavior; the registered projection class
determines the operation. `batch_project`, `batch_patch` and `batch_unproject`
accept a mapper returning `Sequence[int]` and send one task containing the list.
ID validation uses Pydantic and rejects booleans and numeric strings. Each decorator preserves
the wrapped function's return value and publishes only after it returns.

Decorators do not inspect transactions or retry errors. In the example,
`transactional` commits before returning when it owns the transaction; nested
transaction placement remains the application's responsibility. A mapper or
publication error can therefore occur after commit. Native `kiq` reports a
transport failure as `SendTaskError` with the original exception as its cause;
the decorator does not roll back committed work or rerun the command.

### Optional failure storage and periodic repair

Enable `tasks.projection.repair` to record terminal execution failures and
periodically publish batches for repair. This is independent of retry: without
a RetryPolicy the first execution error is terminal; with a policy it is stored
after native SmartRetry exhausts its attempts. Only source projections explicitly
listed in `targets` participate.

```yaml
tasks:
  projection:
    url: amqp://guest:guest@localhost:5672/
    exchange: shop.projection
    prefetch: 10
    repair:
      interval: 30
      batch_size: 1000
      concurrency: 4
      max_attempts: 5
      max_pending: 100000
      prefix: fastamu.projection.failures
      targets:
        "shop.products.app.projections:ProductPrice": "shop.products.app.projections:RebuildPrices"
        "shop.products.app.projections:ProductStock": "shop.products.app.projections:RebuildStocks"
```

Keys and values are the exact registered task names (`module:qualname`). They
are looked up in the existing Register, never dynamically imported. Startup
rejects unknown names and targets that are not batch projections. Targets can
be full-document, patch or delete batches. A batch can map to itself if its
operation is appropriate for repair.

There is nothing to migrate. Failures live in Redis lists on the client the
application already configures, one list per projection: `<prefix>:<task name>`,
plus `<prefix>:<task name>:dead`. Disabling repair creates no queue, no repair
task and no keys.

Redis rather than the application database, for one reason: a failure must be
recordable when the database write path is what is broken. Storing the safety
net in the system that just failed loses it exactly when it is needed. The cost
is accepted deliberately — these keys are a work queue, not a ledger, and the
source of truth stays in SQL — so a Redis flush loses pending repairs the same
way a crash before publication does.

Use the same independent projection worker and scheduler:

```bash
taskiq worker fastamu.tasks.projection.broker:broker --workers 1 --max-async-tasks 10
taskiq scheduler fastamu.tasks.projection.scheduler:scheduler --update-interval 1
```

The scheduler uses native `LabelScheduleSource` for the periodic repair task;
Redis is needed only if delayed retry is also configured. It publishes a tick
to `<exchange>.repair`. A projection worker reads and groups the records and
publishes each group to the selected batch's queue. The scheduler itself does
not open a database connection or execute projections. There is no SyncProjection
or SchedulerPolicy on projection classes.

`targets.resolve()` checks the source-to-target mapping at import, before any
worker starts. `Repair.run()` then takes up to `batch_size` records from each
projection's list, **runs** that projection's batch target itself, and hands back
whatever the result did not settle. Repair executes rather than publishes: no
message, no reservation token, no lease, no correlation label. Publication is
not repair, so nothing is settled on a promise; the work is finished by the same
call that took it.

Projections repair concurrently up to `concurrency` (default 4) because they
share nothing, and the bound is what stops one tick from opening a destination
write and a container scope per projection at once. A projection whose run
raises has its whole batch handed back; a queue that is unreachable is logged and
skipped without abandoning the projections whose records are already taken. The
return value counts records that left the queue settled.

Taking pops. Two overlapping ticks therefore cannot receive the same record, and
nothing has to be reserved — but a process that dies between taking and handing
back loses that batch, which is the price of having no lease. A record handed
back goes to the tail with one attempt spent; `max_attempts` (default 5, and
unrelated to a `RetryPolicy`'s per-execution attempts) bounds how long it can
cycle. Spending them all moves it to `<prefix>:<task name>:dead` with a warning
naming the inputs, where `LRANGE` finds it and it can be drained deliberately —
rather than retried forever or dropped silently. A new failure for the same ID is
a new record with its own budget. `max_pending` caps a list, dropping the oldest
with a warning, so a failure storm cannot exhaust Redis memory.

Repair targets must return one `BulkItemResult` per input ID, with `id=str(input_id)`.
Missing results remain pending; contradictory results for one ID count as failure.
For normal source batch failures, successful IDs are filtered only if the result
ID set matches the input ID set; otherwise all input IDs are retained conservatively.
Single/fanout failures record their input ID, not their destination document IDs.
The application must adapt result IDs when its destination IDs differ.

Repair is not a document lock and promises nothing about exactly-once execution:
a normal write and a repair can still overlap, so batch repair must rebuild
current state or otherwise tolerate replay.

Records are taken oldest first and recovery is not restricted to a recent-time
window, so an old unresolved record stays in line. `batch_size` is a ceiling:
a list holding less returns less, and two ticks split what is there.

Failure recording errors propagate before default `when_saved` ACK. They can
leave deliveries unacknowledged until the channel is released; there is no custom
receiver/requeue loop. Recording, broker ACK and projection writes are separate
operations. This feature does not see messages that never reached the worker and
is not an outbox or an atomic SQL/Elasticsearch transaction.

For custom storage, implement the `FailureStore` protocol in
`messaging/projections/repair/records.py` — `record`, `take`, `requeue` — and
compose `ProjectionFailureMiddleware` and `Repair` with it in your own worker
bootstrap. Three operations and no reservation protocol is the point: the same
contract is satisfiable by a SQL table or a file, not only by a Redis list. The
built-in configuration selects `RedisFailureQueue`. When composing middlewares
manually, install failure middleware **before** SmartRetry and Dishka: Taskiq
runs error hooks in reverse order, allowing scope cleanup and retry scheduling to
happen before terminal-failure recording.

### Optional projection retry

Declare a policy on the concrete class (including patch, delete, batch, fanout
operations). Without a policy the registered task has `retry_on_error=False`.

```python
from typing import ClassVar
from fastamu.messaging.projections.contracts.policies import RetryPolicy

class ProductProjection(AbstractProjection[Product, ProductDocument]):
    queue_name: ClassVar[str] = "products"
    retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
        max_attempts=3, delay=5,
    )
    # Implement the usual source, conversion and destination hooks.
```

`max_attempts` includes the initial execution; `1` means no repeat. `delay` is
the fixed minimum wait in seconds before a retry, not a delay on the initial
publication. Scheduler polling and worker load add latency. Policy settings
are validated by Pydantic; unsupported fields are rejected. Direct instance
calls do not retry. An inherited policy can be disabled with `retry_policy=None`.

Configure the optional Redis schedule source alongside the RabbitMQ settings:

```yaml
tasks:
  projection:
    url: amqp://guest:guest@localhost:5672/
    exchange: fastamu.projection
    prefetch: 10
    retry:
      url: redis://localhost:6379/1
      prefix: shop.projection.retry
      max_connection_pool_size: 25
      buffer_size: 100
      socket_timeout: 5
```

Use Redis 6.2+ (the source uses `GETDEL`), persistence appropriate to the
application, and a prefix unique to this application/environment. Prefixes
cannot contain `:` because of the native source's time-key parser. Worker and
scheduler must use the same settings and projection definitions. A policy
without the Redis configuration fails at startup instead of silently disabling
retry. Without retry configuration no Redis retry source is created.

Run **one** scheduler for this prefix, separately from the projection worker:

```bash
taskiq scheduler fastamu.tasks.projection.scheduler:scheduler --update-interval 1
```

This uses native `TaskiqScheduler` and `ListRedisScheduleSource`; it does not use
the jobs worker or construct a projection DI container. The worker installs
native `SmartRetryMiddleware`. Register maps attempts to `max_retries` (Taskiq
0.12.1 counts total attempts), enables `retry_on_error`, and records
`projection_retry_delay`. `RetryLabelsMiddleware` exposes that delay to SmartRetry
during execution and removes the transport `delay` before sending to RabbitMQ.
This prevents both delayed initial publication and a second transport delay.
Native retry preserves task ID, arguments and destination queue; Dishka closes
the failed scope before scheduling and opens another for the next attempt.

Retry repeats the whole task with the original IDs: a partial batch failure
can repeat successful items. Choose a policy only when
repetition is appropriate. Jitter, backoff and exception filters are not exposed
as per-class options because this native middleware configures them globally.

This is bounded execution retry, not durable failure storage or exactly-once
delivery. After exhaustion, Taskiq logs/returns the error. A failure record is
written only if the optional repair mapping covers that source projection. With the default `when_saved` acknowledgement mode, failure
to store a retry propagates and leaves the original Rabbit delivery unacknowledged;
redelivery requires the delivery/channel to be released, not just Redis recovery.
The native Redis source uses separate writes for schedule data and its time
index. The scheduler also has no leader election: multiple scheduler processes
can publish duplicates. In Taskiq 0.12.1 a failed scheduled publication is marked
as attempted in scheduler memory; restart the scheduler to retry a schedule
still present in Redis. These are limits of this step, not guarantees hidden by
custom retry code. Optional failure storage and periodic repair do not remove those native limits.

`ListRedisScheduleSource` reads current/overdue schedules in batches but, with
overdue recovery enabled, scans Redis keys on every refresh in version 1.2.1.
`buffer_size` controls reads, not concurrency. Use a Redis database with a small
keyspace and tune `--update-interval` against recovery latency and load. The
source's missing pool cleanup in that version is handled at broker shutdown.

References: [native SmartRetry](https://taskiq-python.github.io/available-components/middlewares.html)
and [Redis schedule sources](https://github.com/taskiq-python/taskiq-redis#schedule-sources).

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
| `pg` | A `DBConnection[PostgreSQLUnitOfWork]` on the test DSN |
| `uow` | An open `PostgreSQLUnitOfWork`; use `uow.transaction()` for writes that must commit |
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

## Database backends

Configure the async driver in `db.dsn`; select the matching repository class
explicitly. Install the relevant extras (`mysql`, `sqlite`, `mssql`, `oracle`).
The core connection supplies sessions and never chooses a repository.

| Backend | Write implementation | Upsert API |
|---|---|---|
| PostgreSQL | INSERT/UPDATE RETURNING; VALUES-based bulk update | ON CONFLICT, returns models |
| MySQL | ORM create; count-returning bulk_insert; derived-table bulk update | ON DUPLICATE KEY UPDATE, returns affected-row count |
| MariaDB 10.5+ | INSERT RETURNING; derived-table bulk update, returns count | Native upsert RETURNING |
| SQLite 3.35+ | INSERT/UPDATE RETURNING; VALUES CTE bulk update | ON CONFLICT, returns models |
| SQL Server | Native OUTPUT and VALUES-based bulk update | Not exposed |
| Oracle | Native RETURNING, executemany insert and correlated input-relation bulk update | Not exposed |

Portable field helpers remain available. `JSONField` uses JSONB on PostgreSQL,
native JSON where supported, and serialized text on Oracle. PostgreSQL-only
`JSONBField` and `ArrayField` are in `fastamu.infra.db.dialects.postgresql`.

Repository tests exercise SQLite and the ORM flush/refresh path on SQLite.
Native SQL compilation tests cover the database families. Set
`FASTAMU_TEST_POSTGRESQL`, `FASTAMU_TEST_MYSQL`, `FASTAMU_TEST_MARIADB`,
`FASTAMU_TEST_ORACLE`, or `FASTAMU_TEST_MSSQL` to run the same behavioral suite
against actual servers. Compilation and SQLite tests do not establish live
compatibility with those servers.

The [database benchmark report](benchmarks/results/REPORT.md) records live
measurements on all six backends and includes reproduction scripts. Large
bulk updates still have measured limitations: Oracle timed out at 1,000 rows,
and SQL Server rejected statements exceeding its parameter budget. Successful
smaller batches do not establish a universal safe batch size; column count
also affects the number of parameters.
