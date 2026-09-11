import subprocess
import sys


def test_bootstrap_has_no_messaging_tables_or_worker_imports():
    script = """
import sys
from sqlmodel import SQLModel
from fastamu.core.bootstrap import Bootstrapper
assert "fastamu_projection_versions" not in SQLModel.metadata.tables
bootstrap = Bootstrapper(base_pkgs=())
bootstrap.boot_sqlmodels()
bootstrap.boot_sqlmodels()
assert not SQLModel.metadata.tables
assert "fastamu.tasks.projection.broker" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)
