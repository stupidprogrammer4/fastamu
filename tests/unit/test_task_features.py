import builtins
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from fastamu import scaffold
from fastamu.core.config import ProjectionConfig, Settings
from fastamu.manager import app


def test_minimal_project_omits_optional_backends_and_es():
    files = scaffold.files("shop", "Shop")
    config = Settings.model_validate(yaml.safe_load(files["config.yml"]))
    assert config.tasks.events is None
    assert config.tasks.projection is None
    assert config.tasks.schedulers is None
    assert config.es is None
    assert '"fastamu"' in files["pyproject.toml"]


def test_cli_features_add_independent_config_and_extras(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "new",
            "shop",
            "--dir",
            str(tmp_path / "shop"),
            "--cqrs",
            "--events",
            "--scheduler",
        ],
    )
    assert result.exit_code == 0, result.output
    root = tmp_path / "shop"
    config = Settings.model_validate(
        yaml.safe_load((root / "config.yml").read_text())
    )
    assert config.tasks.projection.prefetch == 1
    assert config.tasks.events.broker == "rabbitmq"
    assert config.tasks.schedulers.broker == "redis"
    assert (
        "fastamu[cqrs,scheduler,events]"
        in (root / "pyproject.toml").read_text()
    )


def test_projection_rejects_non_serial_prefetch_and_missing_es():
    with pytest.raises(ValidationError):
        ProjectionConfig(url="amqp://localhost", prefetch=2)
    files = scaffold.files("shop", "Shop", cqrs=True)
    raw = yaml.safe_load(files["config.yml"])
    raw.pop("es")
    with pytest.raises(ValidationError, match="requires es"):
        Settings.model_validate(raw)


async def test_disabled_backends_are_not_imported_or_connected(monkeypatch):
    from fastamu.core.config import TasksConfig
    from fastamu.tasks import lifespan

    monkeypatch.setattr(
        lifespan, "get_settings", lambda: SimpleNamespace(tasks=TasksConfig())
    )
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(
            (
                "fastamu.tasks.events",
                "fastamu.tasks.projection",
                "fastamu.tasks.schedulers",
            )
        )
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    async with lifespan.task_lifespan():
        pass
