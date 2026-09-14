"""Generate an application project."""

import json
import keyword
from collections.abc import Sequence
from pathlib import Path

import yaml

from .options import Infrastructure
from .templates import render


def files(
    package: str,
    name: str,
    *,
    cqrs: bool = False,
    infra: Sequence[Infrastructure] = (),
) -> dict[str, str]:
    """The project, as a path -> body map.

    Args:
        package (str): The python package the app's modules live in.
        name (str): The project's display name.
    Returns:
        (dict[str, str]): Every file to write, relative to the project root.
    """
    if not package.isidentifier() or keyword.iskeyword(package):
        raise ValueError(f"{package!r} is not a Python package name")
    selected = set(infra)
    if cqrs:
        selected.update((Infrastructure.POSTGRESQL, Infrastructure.ES))
    if Infrastructure.RATE_LIMIT in selected:
        selected.add(Infrastructure.REDIS)
    layout = {
        "config.yml.sample": "project/config_yml.tpl",
        "config.yml": "project/config_yml.tpl",
        "alembic.ini": "project/alembic_ini.tpl",
        "pyproject.toml": "project/pyproject.tpl",
        "pytest.ini": "project/pytest_ini.tpl",
        ".gitignore": "project/gitignore.tpl",
        "README.md": "project/readme.tpl",
        "migrations/env.py": "project/migrations_env.tpl",
        "migrations/script.py.mako": "project/script_mako.tpl",
        "migrations/versions/.gitkeep": "",
        f"{package}/__init__.py": "",
        f"{package}/main.py": "project/main.tpl",
        f"{package}/modules/__init__.py": "",
        "tests/__init__.py": "",
        "tests/conftest.py": "project/conftest.tpl",
        "tests/unit/__init__.py": "",
        "tests/integration/__init__.py": "",
        "tests/api/__init__.py": "",
        "tests/api/test_smoke.py": "project/smoke_test.tpl",
    }
    imports = [
        "from fastapi import FastAPI",
        "from papilio.api.application import create_app",
        "from papilio.core.config import Settings, get_settings",
    ]
    wiring = []
    checks = []
    for feature, folder, cls, field in (
        (Infrastructure.POSTGRESQL, "db", "PGProvider", "db"),
        (Infrastructure.ES, "es", "ESProvider", "es"),
        (Infrastructure.REDIS, "redis", "RedisProvider", "redis"),
        (Infrastructure.HTTP, "http", "HTTPProvider", "http"),
    ):
        if feature in selected:
            imports.append(
                f"from papilio.infra.{folder}.provider import {cls}"
            )
            checks.append(
                f"    assert settings.{field} is not None, 'Configure {field}'"
            )
            wiring.append(f"        {cls}(settings.{field}),")
    values = {
        "PKG": package,
        "IMPORTS": "\n".join(imports),
        "CHECKS": "\n".join(checks),
        "PROVIDERS": "\n".join(wiring),
        "DEPENDENCY": "papilio["
        + ",".join(sorted({"server", *(str(item) for item in selected)}))
        + "]",
        "NAME": name,
        "MIGRATE": "alembic upgrade head"
        if Infrastructure.POSTGRESQL in selected
        else "",
        "MODULE_FLAGS": ""
        if Infrastructure.POSTGRESQL in selected
        else " --plain",
        "DESCRIPTION": json.dumps(
            f"{name}, built on Papilio", ensure_ascii=False
        ),
    }
    rendered = {
        path: render(body, values) if body else ""
        for path, body in layout.items()
    }
    config = yaml.safe_load(rendered["config.yml"])
    config["app"]["features"] = ["cqrs"] if cqrs else []
    config["fastapi"]["title"] = name
    config["fastapi"]["description"] = f"{name} API"
    for feature, key in (
        (Infrastructure.POSTGRESQL, "db"),
        (Infrastructure.ES, "es"),
        (Infrastructure.REDIS, "redis"),
        (Infrastructure.HTTP, "http"),
    ):
        if feature not in selected:
            config.pop(key, None)
    config["rate_limit"]["enabled"] = Infrastructure.RATE_LIMIT in selected
    if Infrastructure.POSTGRESQL not in selected:
        for path in tuple(rendered):
            if path == "alembic.ini" or path.startswith("migrations/"):
                del rendered[path]
    for path in ("config.yml", "config.yml.sample"):
        rendered[path] = yaml.safe_dump(config, sort_keys=False)
    return rendered


def write(
    root: Path,
    package: str,
    name: str,
    *,
    cqrs: bool = False,
    infra: Sequence[Infrastructure] = (),
) -> list[Path]:
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} already exists and is not empty")
    written = []
    for rel, body in files(package, name, cqrs=cqrs, infra=infra).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
