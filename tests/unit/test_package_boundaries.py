import subprocess
import sys
import tomllib
from pathlib import Path

from papilio.scaffolding import project as scaffold
from papilio.scaffolding.modules import files as module_files


def test_distribution_does_not_require_task_frameworks():
    metadata = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = metadata["project"]["dependencies"]
    assert not any(
        "taskiq" in dep.lower() or "apscheduler" in dep.lower()
        for dep in dependencies
    )
    assert metadata["project"]["name"] == "papilio"
    assert metadata["project"]["scripts"] == {"papilio": "papilio.cli.app:app"}


def test_web_scaffold_does_not_create_task_packages():
    files = module_files("shop.modules", "product", cqrs=True)
    assert "domain/documents.py" in files
    assert "infra/repository.py" in files
    assert not any(path.startswith("tasks/") for path in files)


def test_generated_app_imports_with_task_imports_blocked(tmp_path):
    scaffold.write(tmp_path, "probe", "Probe")
    script = """
import importlib.abc
import sys
class BlockTasks(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'taskiq', 'taskiq_redis', 'taskiq_fastapi',
                   'papilio_tasks', 'fastamu', 'papilio_api'}
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'Web imported {fullname}')
sys.meta_path.insert(0, BlockTasks())
from probe.main import app
assert app.title == 'Probe'
assert not any(name.startswith('papilio.tasks') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


def test_plain_application_does_not_import_optional_infrastructure(tmp_path):
    from papilio.scaffolding import modules

    scaffold.write(tmp_path, "probe", "Probe")
    modules.write(
        tmp_path / "probe/modules", "probe.modules", "health", plain=True
    )
    script = """
import importlib.abc
import sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'sqlalchemy', 'sqlmodel', 'elasticsearch', 'redis',
                   'openpyxl', 'throttled', 'asyncpg', 'aiofiles'}
        if fullname.split('.')[0] in blocked:
            raise AssertionError(f'Optional import: {fullname}')
sys.meta_path.insert(0, BlockInfrastructure())
from probe.main import app
assert app.title == 'Probe'
assert '/health' in app.openapi()['paths']
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)
