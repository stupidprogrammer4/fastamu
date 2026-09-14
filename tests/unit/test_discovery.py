import importlib
import sys
from textwrap import dedent

import pytest

from papilio.core.bootstrap import Bootstrapper


@pytest.mark.parametrize(
    "method,path",
    [
        ("boot_sqlmodels", "infra/tables.py"),
        ("boot_providers", "providers.py"),
        ("boot_documents", "domain/documents.py"),
    ],
)
@pytest.mark.parametrize("broken", [False, True])
def test_discovery_distinguishes_absent_modules_from_broken_imports(
    tmp_path,
    monkeypatch,
    method,
    path,
    broken,
):
    package = "discovery_test"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text("")
    if broken:
        source = root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        (source.parent / "__init__.py").touch(exist_ok=True)
        source.write_text("import unavailable_nested_dependency\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    bootstrap = Bootstrapper(())
    bootstrap.submodules = [package]
    try:
        if broken:
            with pytest.raises(
                ModuleNotFoundError, match="unavailable_nested"
            ):
                getattr(bootstrap, method)()
        else:
            getattr(bootstrap, method)()
    finally:
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]


@pytest.mark.parametrize("imported_base", [True, False])
def test_provider_discovery_registers_only_locally_defined_classes(
    tmp_path,
    monkeypatch,
    imported_base,
):
    package = "provider_discovery_test"
    root = tmp_path / package
    first_source = (
        f"from {package}.shared import SharedProvider\n"
        "class FirstProvider(SharedProvider):\n"
        "    def __init__(self):\n"
        "        super().__init__('first')\n"
        if imported_base
        else (
            "from dishka import Provider\n"
            "class FirstProvider(Provider): pass\n"
        )
    )
    sources = {
        "__init__.py": "",
        "shared.py": dedent("""\
            from dishka import Provider
            class SharedProvider(Provider):
                def __init__(self, label):
                    super().__init__()
                    self.label = label
        """),
        "first/__init__.py": "",
        "first/app/__init__.py": "",
        "first/providers.py": first_source,
        "second/__init__.py": "",
        "second/app/__init__.py": "",
        "second/providers.py": (
            "from dishka import Provider\n"
            f"from {package}.first.providers import FirstProvider\n"
            "class SecondProvider(Provider): pass\n"
        ),
    }
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        providers = Bootstrapper((package,)).boot_providers()
        assert sorted(type(provider).__name__ for provider in providers) == [
            "FirstProvider",
            "SecondProvider",
        ]
        if imported_base:
            first = next(
                p for p in providers if type(p).__name__ == "FirstProvider"
            )
            assert first.label == "first"
    finally:
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]
