from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from papilio.cli.app import app
from papilio.core.config import Settings, get_settings
from papilio.scaffolding import project as scaffold


def test_checked_in_configuration_sample_is_valid():
    raw = yaml.safe_load(Path("config.yml.sample").read_text())
    Settings.model_validate(raw)
    assert "tasks" not in raw


def test_minimal_project_has_only_web_configuration():
    files = scaffold.files("shop", "Shop")
    raw = yaml.safe_load(files["config.yml"])
    config = Settings.model_validate(raw)
    assert "tasks" not in raw
    assert config.es is None
    assert config.app.features == set()
    assert '"papilio[server]"' in files["pyproject.toml"]


def test_cli_cqrs_keeps_web_read_models(tmp_path):
    root = tmp_path / "shop"
    result = CliRunner().invoke(
        app, ["new", "shop", "--dir", str(root), "--cqrs"]
    )
    assert result.exit_code == 0, result.output
    config = Settings.model_validate(
        yaml.safe_load((root / "config.yml").read_text())
    )
    assert config.es is not None
    assert {feature.value for feature in config.app.features} == {"cqrs"}
    assert "taskiq" not in (root / "pyproject.toml").read_text()


def test_cqrs_requires_es():
    raw = yaml.safe_load(
        scaffold.files("shop", "Shop", cqrs=True)["config.yml"]
    )
    raw.pop("es")
    with pytest.raises(ValidationError, match="requires es"):
        Settings.model_validate(raw)


def test_worker_configuration_is_rejected_by_web_settings():
    raw = yaml.safe_load(scaffold.files("shop", "Shop")["config.yml"])
    raw["tasks"] = {"schedulers": {"url": "redis://localhost"}}
    with pytest.raises(ValidationError, match="Extra inputs"):
        Settings.model_validate(raw)


@pytest.mark.parametrize("option", ["--scheduler", "--tasks"])
def test_web_cli_does_not_offer_worker_scaffolding(option):
    result = CliRunner().invoke(app, ["module", "product", option])
    assert result.exit_code == 2
    assert "No such option" in result.output


def test_application_can_extend_the_framework_settings(monkeypatch, tmp_path):
    package = tmp_path / "shop"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "from papilio.core.config import Settings as FrameworkSettings\n"
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
