"""Project CLI — scaffolds new modules following the agreed structure.

Pass the module as ``<name>`` or ``<group>.<name>`` — a group is a namespace
folder, not a requirement. Write the name in the **singular**
(e.g. ``catalog.category`` or plain ``category``); the folder, the
``src.modules...`` imports and the router prefix/tags are pluralised
automatically (``categories``). Class names stay singular (``CategoryModel``)
while the table name is pluralised (``tbl_categories``). A new group folder is
created on first use.

A ``--context`` module is the exception: it owns no table and no ES document, so
its name is left exactly as written (``pricing`` stays ``pricing``).

Usage::

    python -m src.manager module category                  # CRUD module, no group
    python -m src.manager module catalog.category          # CRUD module in a group
    python -m src.manager module catalog.category --cqrs   # + ES read-model, projection, commands/queries
    python -m src.manager module pricing --context         # pure-logic module (context, reader, no models)
    python -m src.manager module catalog.category --http   # + infra/gateways.py
    python -m src.manager module catalog.category --excel  # + infra/exporters.py
    python -m src.manager module catalog.category --tasks  # + tasks/ (taskiq background tasks)
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


def _split(name: str) -> tuple[str, str]:
    """Split the argument into its optional group and its module name.

    Args:
        name (str): ``<name>`` or ``<group>.<name>`` (``/`` works as a separator too).
    Returns:
        (tuple[str, str]): The group (empty when the module has none) and the raw name.
    """
    parts = [part.strip() for part in name.replace("/", ".").split(".") if part.strip()]
    if not parts or len(parts) > 2:
        raise typer.BadParameter("expected <name> or <group>.<name>, e.g. product or catalog.product")
    group = parts[0].lower() if len(parts) == 2 else ""
    return group, parts[-1]


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


def _render(tpl: str, pascal: str, snake: str, plural: str, dotted: str) -> str:
    """Fill a template.

    Args:
        tpl (str): The template text.
        pascal (str): Singular class prefix (``Product``).
        snake (str): Singular snake name (``product``).
        plural (str): Folder / route name (``products``).
        dotted (str): Dotted path under ``src.modules`` (``catalog.products`` or ``products``).
    Returns:
        (str): The rendered file body.
    """
    return (
        tpl.replace("<<P>>", pascal)
        .replace("<<PL>>", plural)
        .replace("<<S>>", snake)
        .replace("<<M>>", dotted)
    )


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

from src.modules.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from src.modules.<<M>>.domain.models import <<P>>Model


class I<<P>>Service(Protocol):
    async def create(self, data: <<P>>Create) -> <<P>>Model: ...

    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model: ...

    async def get_by_id(self, id: int) -> <<P>>Model: ...

    async def remove(self, id: int) -> <<P>>Model: ...
"""

SERVICES = """from src.common.bases.services import BaseIDService
from src.modules.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from src.modules.<<M>>.domain.models import <<P>>Model
from src.modules.<<M>>.infra.repository import <<P>>Repository


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
from src.modules.<<M>>.domain.models import <<P>>Model


class <<P>>Repository(PGIDRepository[<<P>>Model]):
    ...
"""

REPOSITORY_CQRS = """from src.infra.es.repository import ESRepository
from src.infra.postgres.repository.base import PGIDRepository
from src.modules.<<M>>.domain.documents import <<P>>Document
from src.modules.<<M>>.domain.models import <<P>>Model


class <<P>>Repository(PGIDRepository[<<P>>Model]):
    ...


class <<P>>ESRepository(ESRepository[<<P>>Document]):
    ...
"""

PROJECTIONS = """from src.common.bases.projection import AbstractESProjection
from src.modules.<<M>>.infra.repository import <<P>>ESRepository, <<P>>Repository


class <<P>>Projection(AbstractESProjection[<<P>>Repository, <<P>>ESRepository]):
    async def project(self, id: int) -> bool:
        # read the PG row, then save the mapped <<P>>Document into ES
        return True
"""

GATEWAYS = "# HTTP gateways for the <<S>> module\n"

EXPORTERS = "# excel/file exporters for the <<S>> module\n"

PROVIDERS = """from dishka import Provider, Scope, provide

from src.modules.<<M>>.interfaces import I<<P>>Service
from src.modules.<<M>>.app.services import <<P>>Service
from src.modules.<<M>>.infra.repository import <<P>>Repository


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

PROVIDERS_CQRS = """from dishka import Provider, Scope, provide

from src.modules.<<M>>.interfaces import I<<P>>Service
from src.modules.<<M>>.app.services import <<P>>Service
from src.modules.<<M>>.infra.projections import <<P>>Projection
from src.modules.<<M>>.infra.repository import <<P>>ESRepository, <<P>>Repository


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_es_repo = provide(<<P>>ESRepository)
    <<S>>_projection = provide(<<P>>Projection)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

COMMANDS = """from src.modules.<<M>>.domain.dtos import <<P>>Create
from src.modules.<<M>>.domain.models import <<P>>Model
from src.modules.<<M>>.infra.projections import <<P>>Projection
from src.modules.<<M>>.infra.repository import <<P>>Repository
from src.tasks.projection import project


class <<P>>CreateCommand:
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    @project(<<P>>Projection)
    async def execute(self, data: <<P>>Create) -> <<P>>Model:
        raise NotImplementedError
"""

QUERIES = """from src.modules.<<M>>.infra.repository import <<P>>ESRepository


class <<P>>SearchQuery:
    def __init__(self, repo: <<P>>ESRepository) -> None:
        self.repo = repo
"""

ROUTERS = """from fastapi import APIRouter

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"])
"""

TASKS = "# taskiq background tasks for the <<S>> module\n"

# --- context-module templates ---------------------------------------------------

CONTEXT = """from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class <<P>>Context:
    \"\"\"Everything the <<S>> logic needs to produce a result.

    Read once at the edge, then never touched again — the logic below it is a
    pure function of this context and the input.
    \"\"\"
"""

CONTEXT_DTOS = """from src.common.bases.dtos import BaseDTO


class <<P>>Input(BaseDTO):
    ...
"""

CONTEXT_SCHEMAS = """from src.common.bases.schemas import BaseOutput


class <<P>>Out(BaseOutput):
    ...
"""

CONTEXT_READERS = """from src.infra.postgres.repository.base import PGReader
from src.modules.<<M>>.domain.context import <<P>>Context


class <<P>>Reader(PGReader):
    \"\"\"Reads the specific columns the <<S>> logic runs on — nothing more.

    It owns no table: one statement selects exactly the fields it needs and
    returns them as a <<P>>Context.
    \"\"\"

    async def read(self) -> <<P>>Context:
        raise NotImplementedError
"""

CONTEXT_INTERFACES = """from typing import Protocol

from src.modules.<<M>>.domain.dtos import <<P>>Input
from src.modules.<<M>>.domain.schemas import <<P>>Out


class I<<P>>Service(Protocol):
    async def run(self, data: <<P>>Input) -> <<P>>Out: ...
"""

CONTEXT_SERVICES = """from src.modules.<<M>>.domain.context import <<P>>Context
from src.modules.<<M>>.domain.dtos import <<P>>Input
from src.modules.<<M>>.domain.schemas import <<P>>Out
from src.modules.<<M>>.infra.readers import <<P>>Reader


class <<P>>Service:
    \"\"\"The <<S>> engine.

    ``run`` is the only place that touches I/O: it reads the context, then hands
    it to ``calculate``, which stays pure and directly unit-testable.
    \"\"\"

    def __init__(self, reader: <<P>>Reader) -> None:
        self.reader = reader

    async def run(self, data: <<P>>Input) -> <<P>>Out:
        context = await self.reader.read()
        return self.calculate(context, data)

    def calculate(self, context: <<P>>Context, data: <<P>>Input) -> <<P>>Out:
        raise NotImplementedError
"""

CONTEXT_PROVIDERS = """from dishka import Provider, Scope, provide

from src.modules.<<M>>.interfaces import I<<P>>Service
from src.modules.<<M>>.app.services import <<P>>Service
from src.modules.<<M>>.infra.readers import <<P>>Reader


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_reader = provide(<<P>>Reader)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""


def _layout(*, cqrs: bool, context: bool, http: bool, excel: bool, tasks: bool) -> dict[str, str]:
    """The files a module is made of, as ``relative path -> template``."""
    if context:
        files = {
            "__init__.py": "",
            "interfaces.py": CONTEXT_INTERFACES,
            "providers.py": CONTEXT_PROVIDERS,
            "domain/__init__.py": "",
            "domain/context.py": CONTEXT,
            "domain/dtos.py": CONTEXT_DTOS,
            "domain/schemas.py": CONTEXT_SCHEMAS,
            "domain/enums.py": ENUMS,
            "app/__init__.py": "",
            "app/services.py": CONTEXT_SERVICES,
            "app/helpers.py": HELPERS,
            "infra/__init__.py": "",
            "infra/readers.py": CONTEXT_READERS,
            "routers/__init__.py": "",
            "routers/admin.py": ROUTERS,
        }
    else:
        files = {
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
    name: str = typer.Argument(
        ..., help="module as <singular-name> or <group>.<singular-name>, e.g. product or catalog.product"
    ),
    cqrs: bool = typer.Option(False, "--cqrs", help="add ES read-model + projection"),
    context: bool = typer.Option(False, "--context", help="pure-logic module: a context + reader, no models"),
    http: bool = typer.Option(False, "--http", help="add infra/gateways.py (HTTP client)"),
    excel: bool = typer.Option(False, "--excel", help="add infra/exporters.py (excel/file)"),
    tasks: bool = typer.Option(False, "--tasks", help="add tasks/ (taskiq background tasks)"),
) -> None:
    """Scaffold a new module under src/modules/[<group>/]<name>."""
    if cqrs and context:
        raise typer.BadParameter("--context owns no table, so it cannot be --cqrs")

    group, raw = _split(name)
    snake, pascal = _names(raw)
    if not snake:
        raise typer.BadParameter("module name is empty")
    # a context module is an engine, not a collection of rows — its name stays as written
    folder = snake if context else _pluralize(snake)
    dotted = f"{group}.{folder}" if group else folder

    parent_dir = MODULES_DIR / group if group else MODULES_DIR
    module_dir = parent_dir / folder
    if module_dir.exists():
        typer.secho(f"module '{dotted}' already exists at {module_dir}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    parent_dir.mkdir(parents=True, exist_ok=True)
    (MODULES_DIR / "__init__.py").touch(exist_ok=True)
    (parent_dir / "__init__.py").touch(exist_ok=True)

    for rel, tpl in _layout(cqrs=cqrs, context=context, http=http, excel=excel, tasks=tasks).items():
        path = module_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(tpl, pascal, snake, folder, dotted), encoding="utf-8")

    kind = "context" if context else "CQRS" if cqrs else "CRUD"
    typer.secho(f"✓ created {kind} module '{dotted}' at {module_dir}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
