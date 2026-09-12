import importlib

import pytest

from fastamu.core.bootstrap import Bootstrapper
from fastamu.manager import _layout


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    root = tmp_path / "discovery_probe"
    root.mkdir()
    (root / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    bootstrapper = Bootstrapper(())
    bootstrapper.submodules = ["discovery_probe"]
    yield root, bootstrapper
    import sys

    for name in list(sys.modules):
        if name == "discovery_probe" or name.startswith("discovery_probe."):
            del sys.modules[name]


def write_module(root, path, body):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    parent = file.parent
    while parent != root:
        (parent / "__init__.py").touch()
        parent = parent.parent
    file.write_text(body)
    importlib.invalidate_caches()


def test_missing_task_packages_are_optional(discovery):
    _, bootstrapper = discovery
    bootstrapper.boot_schedulers()
    assert bootstrapper.boot_projections() == []


def test_scheduler_discovery_does_not_import_event_handlers(discovery):
    root, bootstrapper = discovery
    write_module(root, "tasks/schedulers/jobs.py", "registered = True\n")
    write_module(
        root, "tasks/events/subscribers/orders.py", "raise RuntimeError\n"
    )
    write_module(
        root, "tasks/events/publishers/orders.py", "raise RuntimeError\n"
    )
    bootstrapper.boot_schedulers()
    module = importlib.import_module("discovery_probe.tasks.schedulers.jobs")
    assert module.registered


def test_broken_import_is_not_silently_skipped(discovery):
    root, bootstrapper = discovery
    write_module(
        root,
        "tasks/schedulers/orders.py",
        "import missing_job_dependency\n",
    )
    with pytest.raises(ModuleNotFoundError, match="missing_job_dependency"):
        bootstrapper.boot_schedulers()


def test_scaffold_creates_scheduler_task_packages():
    files = _layout(
        cqrs=False, context=False, http=False, excel=False, tasks=True
    )
    assert files["tasks/schedulers/__init__.py"] == ""
    assert "tasks/schedulers/jobs.py" in files
    assert "tasks/jobs.py" not in files
    assert not any(path.startswith("tasks/projection") for path in files)


def test_cqrs_scaffold_keeps_documents_and_repositories():
    files = _layout(
        cqrs=True, context=False, http=False, excel=False, tasks=False
    )

    assert "domain/documents.py" in files
    assert "infra/repository.py" in files
    assert "infra/projections.py" not in files
    assert not any(path.startswith("tasks/") for path in files)


@pytest.mark.parametrize(
    "path", ["app/projections.py", "app/projections/item.py"]
)
def test_projection_discovery_finds_concrete_local_classes(discovery, path):
    root, bootstrapper = discovery
    write_module(
        root,
        path,
        "from fastamu.messaging.projections.contracts.delete import (\n"
        "    AbstractUnProjection,\n"
        ")\n"
        "class AbstractDelete(AbstractUnProjection):\n"
        "    pass\n"
        "class DeleteProduct(AbstractDelete):\n"
        "    queue_name = 'products'\n"
        "    async def _es_query(self, id: int) -> None:\n"
        "        pass\n"
        "Alias = DeleteProduct\n",
    )
    write_module(root, "tasks/schedulers/jobs.py", "raise RuntimeError\n")
    write_module(root, "tasks/events/events.py", "raise RuntimeError\n")

    projections = bootstrapper.boot_projections()
    assert len(projections) == 1
    assert projections[0].__name__ == "DeleteProduct"
    assert projections[0].queue_name == "products"
    assert bootstrapper.boot_projections() == projections


def test_projection_discovery_does_not_register_reexports_twice(discovery):
    root, bootstrapper = discovery
    write_module(
        root,
        "app/projections/item.py",
        "from fastamu.messaging.projections.contracts.delete import (\n"
        "    AbstractUnProjection,\n"
        ")\n"
        "class DeleteProduct(AbstractUnProjection):\n"
        "    queue_name = 'products'\n"
        "    async def _es_query(self, id: int) -> None:\n"
        "        pass\n",
    )
    write_module(
        root,
        "app/projections/alias.py",
        "from .item import DeleteProduct\n",
    )
    assert len(bootstrapper.boot_projections()) == 1


def test_broken_projection_import_is_not_silently_skipped(discovery):
    root, bootstrapper = discovery
    write_module(
        root, "app/projections.py", "import missing_projection_dependency\n"
    )
    with pytest.raises(
        ModuleNotFoundError, match="missing_projection_dependency"
    ):
        bootstrapper.boot_projections()
