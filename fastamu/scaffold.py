"""The project generator behind `fastamu new`.

What it writes is deliberately thin: a package for your modules, the config
the framework reads, and the alembic wiring — everything else already lives in
the installed package, so there is no framework source to keep in step.
"""

from __future__ import annotations

from pathlib import Path

CONFIG_YML = """app:
  modules:
    - "<<PKG>>.modules"

fastapi:
  title: "<<NAME>>"
  description: "<<NAME>> API"
  version: "0.0.0"

tasks:
  events:
    broker: "rabbitmq"  # rabbitmq | redis
    url: "amqp://guest:guest@localhost:5672/"
    # For Redis: broker: "redis", url: "redis://localhost:6379/0"

  schedulers:
    # taskiq — jobs and cron. Retry is not configured here: whether repeating a
    # job is safe belongs to the module defining it.
    broker: "redis"            # redis
    url: "redis://0.0.0.0:6379/0"
    max_connection_pool_size: 25
    result_ex_time: 86400      # how long a job result stays in redis
  projection:
    broker: "rabbitmq"
    url: "amqp://guest:guest@localhost:5672/"
    prefetch: 1
    max_retries: 3
    retry_delay: 1.0

db:
  test_dsn: "postgresql+asyncpg://postgres:secure_pwd@0.0.0.0:5432/<<PKG>>_test_db"
  dsn: "postgresql+asyncpg://postgres:secure_pwd@0.0.0.0:5432/<<PKG>>_db"
  pool_timeout: 30
  pool_recycle: 1800
  pool_size: 20
  max_overflow: 5

crypto:
  encryption_key: "secret_key="
  password_salt: ""

redis:
  url: "redis://0.0.0.0:6379/0"
  max_connections: 10
  socket_timeout: 5.0
  socket_connect_timeout: 5.0
  health_check_interval: 30

rate_limit:
  enabled: true
  trusted_proxies: []
  general:
    limit: 120
    window_seconds: 60
  rules:
    login:
      limit: 5
      window_seconds: 300
    refresh:
      limit: 20
      window_seconds: 60

jwt:
  algorithm: "HS256"
  secret_key: ""
  access_token_expire_minutes: 60
  api_secret: ""

csrf:
  secret_key: "plSAxBp93Wc9LiuvD0TI_pMWUzf_mlK8SjPB3oROOhU"

storage:
  path: "media"
  temp_dir: "tmp"
  max_file_size: 5242880
  allowed_extensions: ["jpg", "jpeg", "png", "webp"]

es:
  hosts:
    - "http://0.0.0.0:9200"
  username: null
  password: null
  api_key: null
  verify_certs: false
  ca_certs: null

http:
  max_connections: 100
  max_keepalive_connections: 20
  keepalive_expiry: 30.0
  timeout: 15.0
  connect_timeout: 5.0
  follow_redirects: true

logging:
  level: "INFO"
  format: "console"      # "json" in production
  service: "<<PKG>>-api"
"""

ALEMBIC_INI = """[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
path_separator = os
# left as the sentinel on purpose: migrations/env.py fills it from
# db.dsn in config.yml, and the test suite overrides it with test_dsn
sqlalchemy.url = driver://user:pass@localhost/dbname

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

MIGRATIONS_ENV = """import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load every module's models so 'autogenerate' sees the full schema.
from sqlmodel import SQLModel  # noqa: E402

from fastamu.core.bootstrap import get_bootstrapper  # noqa: E402
from fastamu.core.config import get_settings  # noqa: E402

get_bootstrapper().boot_sqlmodels()
target_metadata = SQLModel.metadata

# Database URL comes from app config (config.yml). If one was already set
# programmatically (e.g. tests override it with the test DSN), keep that.
_configured_url = config.get_main_option("sqlalchemy.url")
if not _configured_url or _configured_url.startswith("driver://"):
    config.set_main_option("sqlalchemy.url", get_settings().db.dsn)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    \"\"\"Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    \"\"\"
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    \"\"\"In this scenario we need to create an Engine
    and associate a connection with the context.

    \"\"\"

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    \"\"\"Run migrations in 'online' mode.\"\"\"

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""

SCRIPT_MAKO = """\"\"\"${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

\"\"\"
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    \"\"\"Upgrade schema.\"\"\"
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    \"\"\"Downgrade schema.\"\"\"
    ${downgrades if downgrades else "pass"}
"""

PYTEST_INI = """[pytest]
# Async-first: every `async def` test/fixture runs without an explicit marker
# (pytest-asyncio). The codebase is fully async — sync tests are the exception.
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
asyncio_default_test_loop_scope = session

testpaths = tests
pythonpath = .
addopts = -ra -q --strict-markers

# Run only fast tests:        pytest -m "not integration"
# Run the real-DB/app suite:  pytest -m integration
markers =
    unit: fast, isolated; no external services (tests/unit)
    integration: requires the real test database (tests/integration)
    api: drives the live ASGI app against the test database (tests/api)
"""

GITIGNORE = """# -----------------------------
# Python / FastAPI .gitignore
# -----------------------------

# Bytecode
__pycache__/
*.py[cod]
*$py.class

.claude

# Virtual envs
venv/
.venv/
env/
ENV/
.virtualenv/

# Environment variables / secrets
*.env
*.env.*
!.env.example
!.env.sample

# FastAPI / Uvicorn / Gunicorn logs
*.log
uvicorn.log

# Cache / tooling
.cache/
.pytest_cache/
mypy_cache/
coverage.xml
htmlcov/
*.cover
*.py,cover
.coverage
.coverage.*

# Build / dist
build/
dist/
*.egg-info/
.eggs/

# Static generated files (if using something like templating or builds)
staticfiles/
static/

# IDEs / editors
.idea/
.vscode/
*.swp
*.swo

# OS files
.DS_Store
Thumbs.db

# Docker stuff
docker-data/
docker-volume/

config.yml

*.lock
!frontend/package-lock.json
node_modules/
*.tsbuildinfo
*.zip

seed.sql

storage/*
storage/local/*
test.*

yoyo.ini

test-scripts/*

# uploaded media (runtime data)
media/

# graphify tool cache/output
graphify-out/
"""


PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<<PKG>>"
version = "0.1.0"
description = "<<NAME>>, built on Fastamu"
requires-python = ">=3.13"
dependencies = [
    "fastamu",
]

[project.optional-dependencies]
dev = [
    "pytest==9.0.1",
    "pytest-asyncio==1.3.0",
    "ruff",
]

[tool.hatch.build.targets.wheel]
packages = ["<<PKG>>"]

[tool.ruff]
line-length = 79
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.ruff.lint.isort]
known-first-party = ["<<PKG>>"]
"""

CONFTEST = '''"""The fixtures come from Fastamu.

`fastamu.testing.fixtures` is registered as a pytest plugin, so `pg`, `uow`,
`clean_db`, `dishka_container` and `anonymous` are already available — this
file is where *your* fixtures go.
"""
'''

SMOKE_TEST = '''"""The first test: the app your modules make answers."""

from httpx import AsyncClient


async def test_an_unmatched_path_answers_in_the_error_envelope(
    anonymous: AsyncClient,
) -> None:
    response = await anonymous.get("/nothing-is-here")

    assert response.status_code == 404
    assert response.json()["error"]["message_code"] == "route_not_found"
'''

README = """\
# <<NAME>>

Built on [Fastamu](https://github.com/stupidprogrammer4/fastamu): modules are
discovered, not registered — add one and its router, service, table and jobs
are live.

## Running

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp config.yml.sample config.yml     # fill in the dsn, redis url and secrets
alembic upgrade head

uvicorn fastamu.web.app:app --reload            # the API, on your modules
# Only for features enabled when generating this project:
fastamu projection-worker                     # --cqrs
faststream run fastamu.tasks.events.app:app    # --events
taskiq worker    fastamu.tasks.schedulers.broker:broker    # --scheduler
taskiq scheduler fastamu.tasks.schedulers.scheduler:scheduler
```

Swagger UI is at `/docs`.

## Adding a feature

```bash
fastamu module catalog.product          # or --cqrs / --context / --tasks
alembic revision --autogenerate -m "add products"
alembic upgrade head
```

The module lands in `<<PKG>>/modules/catalog/products/`. Nothing to register:
`app.modules` in `config.yml` tells the bootstrapper where to look.

## Tests

```bash
pytest -m unit           # fast, no services
pytest -m integration    # against db.test_dsn
pytest -m api            # drives the live app
```
"""


def render(text: str, package: str, name: str) -> str:
    return text.replace("<<PKG>>", package).replace("<<NAME>>", name)


def files(
    package: str, name: str, *, cqrs=False, scheduler=False, events=False
) -> dict[str, str]:
    """The project, as a path -> body map.

    Args:
        package (str): The python package the app's modules live in.
        name (str): The project's display name.
    Returns:
        (dict[str, str]): Every file to write, relative to the project root.
    """
    layout = {
        "config.yml.sample": CONFIG_YML,
        "config.yml": CONFIG_YML,
        "alembic.ini": ALEMBIC_INI,
        "pyproject.toml": PYPROJECT,
        "pytest.ini": PYTEST_INI,
        ".gitignore": GITIGNORE,
        "README.md": README,
        "migrations/env.py": MIGRATIONS_ENV,
        "migrations/script.py.mako": SCRIPT_MAKO,
        "migrations/versions/.gitkeep": "",
        f"{package}/__init__.py": "",
        f"{package}/modules/__init__.py": "",
        "tests/__init__.py": "",
        "tests/conftest.py": CONFTEST,
        "tests/unit/__init__.py": "",
        "tests/integration/__init__.py": "",
        "tests/api/__init__.py": "",
        "tests/api/test_smoke.py": SMOKE_TEST,
    }
    import yaml

    rendered = {
        path: render(body, package, name) for path, body in layout.items()
    }
    config = yaml.safe_load(rendered["config.yml"])
    if not cqrs:
        config.pop("es", None)
        config["tasks"].pop("projection", None)
    if not scheduler:
        config["tasks"].pop("schedulers", None)
    if not events:
        config["tasks"].pop("events", None)
    for path in ("config.yml", "config.yml.sample"):
        rendered[path] = yaml.safe_dump(config, sort_keys=False)
    extras = [
        name
        for name, enabled in (
            ("cqrs", cqrs),
            ("scheduler", scheduler),
            ("events", events),
        )
        if enabled
    ]
    if extras:
        dependency = "fastamu[" + ",".join(extras) + "]"
        rendered["pyproject.toml"] = rendered["pyproject.toml"].replace(
            '"fastamu"', f'"{dependency}"'
        )
    return rendered


def write(root: Path, package: str, name: str, **features) -> list[Path]:
    written = []
    for rel, body in files(package, name, **features).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
