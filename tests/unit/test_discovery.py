import importlib
import sys

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
