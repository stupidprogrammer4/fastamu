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
    bootstrapper.boot_projections()
    assert bootstrapper.boot_subscribers() == []
    assert bootstrapper.boot_publishers() == []


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


@pytest.mark.parametrize("backend", ["rabbit", "redis"])
def test_discovers_routers_once_and_keeps_roles_separate(discovery, backend):
    root, bootstrapper = discovery
    cls = "RabbitRouter" if backend == "rabbit" else "RedisRouter"
    body = f"from faststream.{backend} import {cls}\nrouter = {cls}()\n"
    write_module(
        root, "tasks/events/subscribers/orders.py", body + "alias = router\n"
    )
    write_module(root, "tasks/events/publishers/orders.py", body)
    subscribers = bootstrapper.boot_subscribers()
    publishers = bootstrapper.boot_publishers()
    assert len(subscribers) == len(publishers) == 1
    assert subscribers[0] is not publishers[0]
    assert bootstrapper.boot_subscribers() == subscribers


def test_broken_import_is_not_silently_skipped(discovery):
    root, bootstrapper = discovery
    write_module(
        root,
        "tasks/events/subscribers/orders.py",
        "import missing_event_dependency\n",
    )
    with pytest.raises(ModuleNotFoundError, match="missing_event_dependency"):
        bootstrapper.boot_subscribers()


def test_projection_discovery_imports_the_real_infrastructure_module(
    discovery,
):
    root, bootstrapper = discovery
    write_module(root, "infra/projections.py", "registered = True\n")

    bootstrapper.boot_projections()

    module = importlib.import_module("discovery_probe.infra.projections")
    assert module.registered


def test_scaffold_creates_scheduler_and_event_task_packages():
    files = _layout(
        cqrs=False, context=False, http=False, excel=False, tasks=True
    )
    for role in (
        "schedulers",
        "events",
        "events/subscribers",
        "events/publishers",
    ):
        assert files[f"tasks/{role}/__init__.py"] == ""
    assert "tasks/schedulers/jobs.py" in files
    assert "tasks/jobs.py" not in files
    assert not any(path.startswith("tasks/projection") for path in files)


def test_cqrs_scaffold_keeps_projections_beside_its_repositories():
    files = _layout(
        cqrs=True, context=False, http=False, excel=False, tasks=False
    )

    assert "infra/projections.py" in files
    assert not any(path.startswith("tasks/") for path in files)
