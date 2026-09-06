import builtins
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from fastamu import scaffold
from fastamu.core.config import ProjectionConfig, Settings, get_settings
from fastamu.manager import app


def test_minimal_project_omits_optional_backends_and_es():
    files = scaffold.files("shop", "Shop")
    config = Settings.model_validate(yaml.safe_load(files["config.yml"]))
    assert config.tasks.events is None
    assert config.tasks.projection is None
    assert config.tasks.schedulers is None
    assert config.es is None
    assert config.app.features == set()
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
    assert {feature.value for feature in config.app.features} == {
        "cqrs",
        "events",
        "scheduler",
    }
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


def test_feature_and_configuration_must_match():
    raw = yaml.safe_load(scaffold.files("shop", "Shop")["config.yml"])
    raw["app"]["features"] = ["events"]
    with pytest.raises(ValidationError, match="configuration is missing"):
        Settings.model_validate(raw)

    raw["app"]["features"] = []
    raw["tasks"]["events"] = {
        "broker": "rabbitmq",
        "url": "amqp://localhost",
    }
    with pytest.raises(ValidationError, match="requires enabling"):
        Settings.model_validate(raw)


def test_application_can_extend_the_framework_settings(monkeypatch, tmp_path):
    package = tmp_path / "shop"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "from fastamu.core.config import Settings as FrameworkSettings\n"
        "class Settings(FrameworkSettings):\n"
        "    storefront: str\n"
    )
    raw = yaml.safe_load(scaffold.files("shop", "Shop")["config.yml"])
    raw["app"]["settings"] = "shop.config.Settings"
    raw["storefront"] = "goldis"
    (tmp_path / "config.yml").write_text(yaml.safe_dump(raw))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    try:
        assert get_settings().storefront == "goldis"
    finally:
        get_settings.cache_clear()


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
