"""Project CLI — scaffolds new modules following the agreed structure.

Pass the module as ``<name>`` or ``<group>.<name>`` — a group is a namespace
folder, not a requirement. Write the name in the **singular**
(e.g. ``catalog.category`` or plain ``category``); the folder, the
``<app>.modules...`` imports and the router prefix/tags are pluralised
automatically (``categories``). Class names stay singular (``CategoryModel``)
while the table name is pluralised (``tbl_categories``). A new group folder is
created on first use.

A ``--context`` module is the exception: it owns no table and no ES document,
so its name is left exactly as written (``pricing`` stays ``pricing``).

Usage::

    # CRUD module, no group
    python -m fastamu.manager module category
    # CRUD module in a group
    python -m fastamu.manager module catalog.category
    # + ES read-model, commands/queries
    python -m fastamu.manager module catalog.category --cqrs
    # pure-logic module (context, reader, no models)
    python -m fastamu.manager module pricing --context
    # + infra/gateways.py
    python -m fastamu.manager module catalog.category --http
    # + infra/exporters.py
    python -m fastamu.manager module catalog.category --excel
    # + tasks/ (taskiq background tasks)
    python -m fastamu.manager module catalog.category --tasks
    # + only Taskiq jobs
    python -m fastamu.manager module catalog.category --scheduler
    # + only the subscriber or publisher package
    python -m fastamu.manager module catalog.category --subscriber
    python -m fastamu.manager module catalog.category --publisher
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import typer

from fastamu import scaffold
from fastamu.common.utils.strings import pluralize
from fastamu.core.config import get_settings

app = typer.Typer(help="Fastamu project CLI", no_args_is_help=True)

RED = typer.colors.RED
GREEN = typer.colors.GREEN


def _target_package() -> tuple[str, Path]:
    """Where a scaffolded module goes: the first package in `app.modules`.

    Read from the config.yml of the project you are standing in, so the
    generated imports carry your package name and the files land in your tree
    — never inside the installed framework.

    Returns:
        (tuple[str, Path]): The dotted package and its directory.
    """
    try:
        packages = get_settings().app.modules
    except FileNotFoundError:
        raise typer.BadParameter(
            "no config.yml here — run this inside a project "
            "(or create one with `fastamu new <name>`)"
        ) from None
    name = packages[0]
    # a console script does not put the working directory on the path, and a
    # project is not necessarily installed yet — the directory you are
    # standing in is the project root, so treat it as one
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        package = importlib.import_module(name)
    except ModuleNotFoundError:
        raise typer.BadParameter(
            f"app.modules names {name!r}, which is not importable from here"
        ) from None
    return name, Path(next(iter(package.__path__)))


@app.callback()
def _main() -> None:
    """Fastamu project CLI."""


def _split(name: str) -> tuple[str, str]:
    """Split the argument into its optional group and its module name.

    Args:
        name (str): ``<name>`` or ``<group>.<name>`` (``/`` works as a
            separator too).
    Returns:
        (tuple[str, str]): The group (empty when the module has none) and the
            raw name.
    """
    parts = [
        part.strip()
        for part in name.replace("/", ".").split(".")
        if part.strip()
    ]
    if not parts or len(parts) > 2:
        raise typer.BadParameter(
            "expected <name> or <group>.<name>, "
            "e.g. product or catalog.product"
        )
    group = parts[0].lower() if len(parts) == 2 else ""
    return group, parts[-1]


def _names(raw: str) -> tuple[str, str]:
    """(snake, Pascal) from a raw module name like 'product' /
    'product-tag'."""
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


def _render(
    tpl: str, pascal: str, snake: str, plural: str, dotted: str, pkg: str
) -> str:
    """Fill a template.

    Args:
        tpl (str): The template text.
        pascal (str): Singular class prefix (``Product``).
        snake (str): Singular snake name (``product``).
        plural (str): Folder / route name (``products``).
        dotted (str): Dotted path under the app's modules package
            (``catalog.products`` or ``products``).
        pkg (str): The app's modules package, for the generated imports.
    Returns:
        (str): The rendered file body.
    """
    return (
        tpl.replace("<<P>>", pascal)
        .replace("<<PL>>", plural)
        .replace("<<S>>", snake)
        .replace("<<M>>", dotted)
        .replace("<<PKG>>", pkg)
    )


# --- templates --------------------------------------------------------------

MODELS = """from fastamu.common.models.entities import BaseIDTimestampEntity


class <<P>>Model(BaseIDTimestampEntity):
    # fields only — the table that carries them is in infra/tables.py
    ...
"""

TABLES = """from fastamu.infra.db.table import BaseTable
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Table(<<P>>Model, BaseTable, table=True):
    # the table name derives from the class: "tbl_<<PL>>"
    pass
"""

DTOS = """from fastamu.common.schemas.dtos import BaseDTO


class <<P>>Create(BaseDTO): ...


class <<P>>Update(BaseDTO): ...
"""

SCHEMAS = """from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Out(<<P>>Model):
    # subclasses the model, so the fields are declared once; narrow or add
    # here for what the wire should actually carry
    pass
"""

ENUMS = "# enums for the <<S>> module\n"

DOCUMENTS = """from elasticsearch.dsl import AsyncDocument


class <<P>>Document(AsyncDocument):
    class Index:
        name = "<<S>>"
"""

INTERFACES = """from typing import Protocol

from <<PKG>>.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class I<<P>>Service(Protocol):
    async def create(self, data: <<P>>Create) -> <<P>>Model: ...

    async def update(self, id: int, data: <<P>>Update) -> <<P>>Model: ...

    async def get_by_id(self, id: int) -> <<P>>Model: ...

    async def remove(self, id: int) -> <<P>>Model: ...
"""

SERVICES = """from fastamu.common.services import BaseIDService
from <<PKG>>.<<M>>.domain.dtos import <<P>>Create, <<P>>Update
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository


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

REPOSITORY = """\
from fastamu.infra.db.repository import DBIDRepository
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Repository(DBIDRepository[<<P>>Model]): ...
"""

REPOSITORY_CQRS = """from fastamu.infra.es.repository import ESRepository
from fastamu.infra.db.repository import DBIDRepository
from <<PKG>>.<<M>>.domain.documents import <<P>>Document
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Repository(DBIDRepository[<<P>>Model]): ...


class <<P>>ESRepository(ESRepository[<<P>>Document]): ...
"""

GATEWAYS = '''from fastamu.infra.http.gateway import BaseGateway


class <<P>>Gateway(BaseGateway):
    """Outbound calls for the <<S>> module.

    Map the response into this module's own domain types before returning —
    nothing above infra/ should be reading a third party's JSON shape.
    """

    __base_url__ = ""

    async def fetch(self, path: str) -> dict:
        resp = await self.get(path)
        resp.raise_for_status()
        return resp.json()
'''

EXPORTERS = "# excel/file exporters for the <<S>> module\n"

PROVIDERS = """from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

PROVIDERS_CQRS = """from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.repository import (
    <<P>>ESRepository,
    <<P>>Repository,
)
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_es_repo = provide(<<P>>ESRepository)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""

COMMANDS = """from <<PKG>>.<<M>>.domain.dtos import <<P>>Create
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository


class <<P>>CreateCommand:
    def __init__(self, repo: <<P>>Repository) -> None:
        self.repo = repo

    async def execute(self, data: <<P>>Create) -> <<P>>Model:
        raise NotImplementedError
"""

QUERIES = """\
from <<PKG>>.<<M>>.infra.repository import <<P>>ESRepository


class <<P>>SearchQuery:
    def __init__(self, repo: <<P>>ESRepository) -> None:
        self.repo = repo
"""

ROUTERS = """from fastapi import APIRouter

router = APIRouter(prefix="/<<PL>>", tags=["<<PL>>"])
"""

TASKS = "# taskiq background tasks for the <<S>> module\n"

# --- context-module templates -----------------------------------------------

CONTEXT = """from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class <<P>>Context:
    \"\"\"Everything the <<S>> logic needs to produce a result.

    Read once at the edge, then never touched again — the logic below it is a
    pure function of this context and the input.
    \"\"\"
"""

CONTEXT_DTOS = """from fastamu.common.schemas.dtos import BaseDTO


class <<P>>Input(BaseDTO): ...
"""

CONTEXT_SCHEMAS = """from fastamu.common.schemas.outputs import BaseOutput


class <<P>>Out(BaseOutput): ...
"""

CONTEXT_READERS = """\
from fastamu.infra.db.repository import DBReader
from <<PKG>>.<<M>>.domain.context import <<P>>Context


class <<P>>Reader(DBReader):
    \"\"\"Reads the specific columns the <<S>> logic runs on — nothing more.

    It owns no table: one statement selects exactly the fields it needs and
    returns them as a <<P>>Context.
    \"\"\"

    async def read(self) -> <<P>>Context:
        raise NotImplementedError
"""

CONTEXT_INTERFACES = """from typing import Protocol

from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.routers.schemas import <<P>>Out


class I<<P>>Service(Protocol):
    async def run(self, data: <<P>>Input) -> <<P>>Out: ...
"""

CONTEXT_SERVICES = """\
from <<PKG>>.<<M>>.domain.context import <<P>>Context
from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.routers.schemas import <<P>>Out
from <<PKG>>.<<M>>.infra.readers import <<P>>Reader


class <<P>>Service:
    \"\"\"The <<S>> engine.

    ``run`` is the only place that touches I/O: it reads the context,
    then hands it to ``calculate``, which stays pure and testable.
    \"\"\"

    def __init__(self, reader: <<P>>Reader) -> None:
        self.reader = reader

    async def run(self, data: <<P>>Input) -> <<P>>Out:
        context = await self.reader.read()
        return self.calculate(context, data)

    def calculate(
        self, context: <<P>>Context, data: <<P>>Input
    ) -> <<P>>Out:
        raise NotImplementedError
"""

CONTEXT_PROVIDERS = """from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.readers import <<P>>Reader
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_reader = provide(<<P>>Reader)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
"""


def _layout(
    *,
    cqrs: bool,
    context: bool,
    http: bool,
    excel: bool,
    tasks: bool,
    scheduler: bool = False,
) -> dict[str, str]:
    """The files a module is made of, as ``relative path -> template``."""
    if context:
        files = {
            "__init__.py": "",
            "interfaces.py": CONTEXT_INTERFACES,
            "providers.py": CONTEXT_PROVIDERS,
            "domain/__init__.py": "",
            "domain/context.py": CONTEXT,
            "domain/dtos.py": CONTEXT_DTOS,
            "routers/schemas.py": CONTEXT_SCHEMAS,
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
            "domain/entities.py": MODELS,
            "infra/tables.py": TABLES,
            "domain/dtos.py": DTOS,
            "routers/schemas.py": SCHEMAS,
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
            files["app/commands.py"] = COMMANDS
            files["app/queries.py"] = QUERIES
    if tasks or scheduler:
        files["tasks/__init__.py"] = ""
    if tasks or scheduler:
        files["tasks/schedulers/__init__.py"] = ""
        files["tasks/schedulers/jobs.py"] = TASKS
    if http:
        files["infra/gateways.py"] = GATEWAYS
    if excel:
        files["infra/exporters.py"] = EXPORTERS
    return files


@app.command()
def module(
    name: str = typer.Argument(
        ...,
        help=(
            "module as <singular-name> or <group>.<singular-name>, "
            "e.g. product or catalog.product"
        ),
    ),
    cqrs: bool = typer.Option(
        False, "--cqrs", help="add ES read-model + commands/queries"
    ),
    context: bool = typer.Option(
        False,
        "--context",
        help="pure-logic module: a context + reader, no models",
    ),
    http: bool = typer.Option(
        False, "--http", help="add infra/gateways.py (HTTP client)"
    ),
    excel: bool = typer.Option(
        False, "--excel", help="add infra/exporters.py (excel/file)"
    ),
    tasks: bool = typer.Option(
        False, "--tasks", help="add Taskiq scheduled/background jobs"
    ),
    scheduler: bool = typer.Option(
        False, "--scheduler", help="add tasks/schedulers/ (Taskiq jobs)"
    ),
) -> None:
    """Scaffold a module into the app's modules package."""
    if cqrs and context:
        raise typer.BadParameter(
            "--context owns no table, so it cannot be --cqrs"
        )

    group, raw = _split(name)
    snake, pascal = _names(raw)
    if not snake:
        raise typer.BadParameter("module name is empty")
    # a context module is an engine, not a collection of rows — its name
    # stays as written
    folder = snake if context else _pluralize(snake)
    dotted = f"{group}.{folder}" if group else folder

    pkg, modules_dir = _target_package()
    parent_dir = modules_dir / group if group else modules_dir
    module_dir = parent_dir / folder
    if module_dir.exists():
        typer.secho(
            f"module '{dotted}' already exists at {module_dir}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    parent_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / "__init__.py").touch(exist_ok=True)
    (parent_dir / "__init__.py").touch(exist_ok=True)

    for rel, tpl in _layout(
        cqrs=cqrs,
        context=context,
        http=http,
        excel=excel,
        tasks=tasks,
        scheduler=scheduler,
    ).items():
        path = module_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _render(tpl, pascal, snake, folder, dotted, pkg),
            encoding="utf-8",
        )

    kind = "context" if context else "CQRS" if cqrs else "CRUD"
    typer.secho(
        f"✓ created {kind} module '{dotted}' at {module_dir}",
        fg=typer.colors.GREEN,
    )


@app.command()
def new(
    cqrs: bool = typer.Option(False, "--cqrs"),
    scheduler: bool = typer.Option(False, "--scheduler"),
    name: str = typer.Argument(..., help="project name, e.g. shop or my-shop"),
    directory: str = typer.Option(
        "",
        "--dir",
        help="where to create it (default: ./<name>)",
    ),
) -> None:
    """Start a project on Fastamu.

    Writes only what is yours: a package for your modules, the config the
    framework reads, alembic wiring and a test suite. The framework itself
    stays where pip put it, so there is no vendored copy to keep in step —
    upgrading is `pip install -U fastamu`.
    """
    package = name.strip().replace("-", "_").replace(" ", "_").lower()
    if not package.isidentifier():
        raise typer.BadParameter(
            f"{name!r} does not make a python package name"
        )

    root = Path(directory) if directory else Path(package)
    if root.exists() and any(root.iterdir()):
        typer.secho(f"{root} already exists and is not empty", fg=RED)
        raise typer.Exit(code=1)

    scaffold.write(root, package, name, cqrs=cqrs, scheduler=scheduler)
    typer.secho(f"✓ created project '{name}' at {root}", fg=GREEN)
    typer.echo(
        f"\n  cd {root}\n"
        '  pip install -e ".[dev]"\n'
        "  # fill in config.yml, then:\n"
        "  alembic upgrade head\n"
        "  uvicorn fastamu.web.app:app --reload\n"
    )


if __name__ == "__main__":
    app()
