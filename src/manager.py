"""Project CLI — scaffolds new modules following the agreed structure.

Pass the module as ``<group>.<name>`` with the name in the **singular**
(e.g. ``catalog.category``); the folder, the ``src.modules.<group>.<name>``
imports and the router prefix/tags are pluralised automatically
(``categories``). Class names stay singular (``CategoryModel``) while the
table name is pluralised (``tbl_categories``). Groups: catalog, market,
channels, ops (a new group folder is created on first use).

Usage::

    python -m src.cli module catalog.category            # CRUD module
    python -m src.cli module catalog.category --cqrs      # + ES read-model, projection, commands/queries
    python -m src.cli module catalog.category --http      # + infra/gateways.py
    python -m src.cli module catalog.category --excel     # + infra/exporters.py
    python -m src.cli module catalog.category --tasks     # + tasks/ (taskiq background tasks)
"""

from __future__ import annotations

from pathlib import Path

import typer

from src.common.utils.string_utils import pluralize

app = typer.Typer(help="goldis project CLI", no_args_is_help=True)

MODULES_DIR = Path(__file__).resolve().parent / "modules"


@app.callback()
def _main() -> None:
    """goldis project CLI."""


def _names(raw: str) -> tuple[str, str]:
    """(snake, Pascal) from a raw module name like 'product' / 'product-tag'."""
    snake = raw.strip().lower().replace("-", "_").replace(" ", "_")
    pascal = "".join(part.capitalize() for part in snake.split("_") if part)
    return snake, pascal


def _pluralize(snake: str) -> str:
    """Pluralise the last word of a snake_case name (shared heuristics)."""
    parts = snake.split("_")
    result = snake
    if parts[-1]:
        parts[-1] = pluralize(parts[-1])
        result = "_".join(parts)
    return result


def _render(tpl: str, pascal: str, snake: str, plural: str, group: str) -> str:
    return tpl.replace("<<P>>", pascal).replace("<<PL>>", plural).replace("<<S>>", snake).replace("<<G>>", group)


# --- templates ------------------------------------------------------------------

MODELS = """from src.infra.postgres.models.base import BaseIDTimestampModel


class <<P>>Model(BaseIDTimestampModel, table=True):
    # table name auto-derives as "tbl_<<PL>>"; columns combine alias + factory
    ...
"""

DTOS = """from src.common.bases.dtos import BaseDTO


class <<P>>Create(BaseDTO):
    ...


class <<P>>Update(BaseDTO):
    ...
"""

SCHEMAS = """from src.common.bases.schemas import BaseOutput


class <<P>>Out(BaseOutput):
    id: int
"""

ENUMS = "# enums for the <<S>> module\n"

DOCUMENTS = """from elasticsearch.dsl import AsyncDocument


class <<P>>Document(AsyncDocument):
    class Index:
        name = "<<S>>"
"""

INTERFACES = """from typing import Protocol

from src.modules.<<G>>.<<PL>>.domain.dtos import <<P>>Create, <<P>>Update
from src.modules.<<G>>.<<PL>>.domain.models import <<P>>Model


class I<<P>>Service(Protocol):
    async def create(self, data: <<P>>Create) -> <<P>>Model: ...

    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model: ...

    async def get_by_id(self, id: int) -> <<P>>Model: ...

    async def remove(self, id: int) -> <<P>>Model: ...
"""

SERVICES = """from src.common.bases.services import BaseIDService
from src.modules.<<G>>.<<PL>>.domain.dtos import <<P>>Create, <<P>>Update
from src.modules.<<G>>.<<PL>>.domain.models import <<P>>Model
from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>Repository


class <<P>>Service(BaseIDService[<<P>>Model]):
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    async def create(self, data: <<P>>Create) -> <<P>>Model:
        raise NotImplementedError

    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model:
        raise NotImplementedError

    async def get_by_id(self, id: int) -> <<P>>Model:
        raise NotImplementedError

    async def remove(self, id: int) -> <<P>>Model:
        raise NotImplementedError
"""

HELPERS = "# helper functions for the <<S>> module\n"

REPOSITORY = """from src.infra.postgres.repository.base import PGIDRepository
from src.modules.<<G>>.<<PL>>.domain.models import <<P>>Model


class <<P>>Repository(PGIDRepository[<<P>>Model]):
    ...
"""

REPOSITORY_CQRS = """from src.infra.es.repository import ESRepository
from src.infra.postgres.repository.base import PGIDRepository
from src.modules.<<G>>.<<PL>>.domain.documents import <<P>>Document
from src.modules.<<G>>.<<PL>>.domain.models import <<P>>Model


class <<P>>Repository(PGIDRepository[<<P>>Model]):
    ...


class <<P>>ESRepository(ESRepository[<<P>>Document]):
    ...
"""

PROJECTIONS = """from src.common.bases.projection import AbstractESProjection
from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>ESRepository, <<P>>Repository


class <<P>>Projection(AbstractESProjection[<<P>>Repository, <<P>>ESRepository]):
    async def project(self, id: int) -> bool:
        # read the PG row, then save the mapped <<P>>Document into ES
        return True
"""

GATEWAYS = "# HTTP gateways for the <<S>> module\n"

EXPORTERS = "# excel/file exporters for the <<S>> module\n"

PROVIDERS = """from dishka import Provider, Scope, provide

from src.modules.<<G>>.<<PL>>.interfaces import I<<P>>Service
from src.modules.<<G>>.<<PL>>.app.services import <<P>>Service
from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>Repository


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

PROVIDERS_CQRS = """from dishka import Provider, Scope, provide

from src.modules.<<G>>.<<PL>>.interfaces import I<<P>>Service
from src.modules.<<G>>.<<PL>>.app.services import <<P>>Service
from src.modules.<<G>>.<<PL>>.infra.projections import <<P>>Projection
from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>ESRepository, <<P>>Repository


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_es_repo = provide(<<P>>ESRepository)
    <<S>>_projection = provide(<<P>>Projection)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

COMMANDS = """from src.modules.<<G>>.<<PL>>.domain.dtos import <<P>>Create
from src.modules.<<G>>.<<PL>>.domain.models import <<P>>Model
from src.modules.<<G>>.<<PL>>.infra.projections import <<P>>Projection
from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>Repository
from src.tasks.projection import project


class <<P>>CreateCommand:
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    @project(<<P>>Projection)
    async def execute(self, data: <<P>>Create) -> <<P>>Model:
        raise NotImplementedError
"""

QUERIES = """from src.modules.<<G>>.<<PL>>.infra.repository import <<P>>ESRepository


class <<P>>SearchQuery:
    def __init__(self, repo: <<P>>ESRepository) -> None:
        self.repo = repo
"""

ROUTERS = """from fastapi import APIRouter

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"])
"""

TASKS = "# taskiq background tasks for the <<S>> module\n"


def _layout(snake: str, *, cqrs: bool, http: bool, excel: bool, tasks: bool) -> dict[str, str]:
    files: dict[str, str] = {
        "__init__.py": "",
        "interfaces.py": INTERFACES,
        "providers.py": PROVIDERS_CQRS if cqrs else PROVIDERS,
        "domain/__init__.py": "",
        "domain/models.py": MODELS,
        "domain/dtos.py": DTOS,
        "domain/schemas.py": SCHEMAS,
        "domain/enums.py": ENUMS,
        "app/__init__.py": "",
        "app/services.py": SERVICES,
        "app/helpers.py": HELPERS,
        "infra/__init__.py": "",
        "infra/repository.py": REPOSITORY_CQRS if cqrs else REPOSITORY,
        "routers/__init__.py": "",
        "routers/admin.py": ROUTERS,
    }
    if cqrs:
        files["domain/documents.py"] = DOCUMENTS
        files["infra/projections.py"] = PROJECTIONS
        files["app/commands.py"] = COMMANDS
        files["app/queries.py"] = QUERIES
    if tasks:
        files["tasks/__init__.py"] = ""
        files["tasks/jobs.py"] = TASKS
    if http:
        files["infra/gateways.py"] = GATEWAYS
    if excel:
        files["infra/exporters.py"] = EXPORTERS
    return files


@app.command()
def module(
    name: str = typer.Argument(..., help="module as <group>.<singular-name>, e.g. catalog.category"),
    cqrs: bool = typer.Option(False, "--cqrs", help="add ES read-model + projection"),
    http: bool = typer.Option(False, "--http", help="add infra/gateways.py (HTTP client)"),
    excel: bool = typer.Option(False, "--excel", help="add infra/exporters.py (excel/file)"),
    tasks: bool = typer.Option(False, "--tasks", help="add tasks/ (taskiq background tasks)"),
) -> None:
    """Scaffold a new module under src/modules/<group>/<plural-name>."""
    group, sep, raw = name.replace("/", ".").partition(".")
    if not sep or not group.strip() or "." in raw:
        raise typer.BadParameter("expected <group>.<name>, e.g. catalog.category")
    group = group.strip().lower()
    snake, pascal = _names(raw)
    if not snake:
        raise typer.BadParameter("module name is empty")
    plural = _pluralize(snake)

    group_dir = MODULES_DIR / group
    module_dir = group_dir / plural
    if module_dir.exists():
        typer.secho(f"module '{group}.{plural}' already exists at {module_dir}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    group_dir.mkdir(parents=True, exist_ok=True)
    (MODULES_DIR / "__init__.py").touch(exist_ok=True)
    (group_dir / "__init__.py").touch(exist_ok=True)

    for rel, tpl in _layout(snake, cqrs=cqrs, http=http, excel=excel, tasks=tasks).items():
        path = module_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(tpl, pascal, snake, plural, group), encoding="utf-8")

    kind = "CQRS" if cqrs else "CRUD"
    typer.secho(f"✓ created {kind} module '{group}.{plural}' at {module_dir}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
