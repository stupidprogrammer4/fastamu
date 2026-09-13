import subprocess
import sys


def test_bootstrap_has_no_application_modules_tables_or_routers():
    script = """
import sys
from importlib.util import find_spec
from sqlmodel import SQLModel
from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import AppConfig
assert find_spec("papilio.modules") is None
assert AppConfig().modules == []
assert "papilio_projection_versions" not in SQLModel.metadata.tables
bootstrap = Bootstrapper()
bootstrap.boot_sqlmodels()
bootstrap.boot_sqlmodels()
assert not SQLModel.metadata.tables
assert bootstrap.boot_providers() == []
assert bootstrap.boot_routers() == []
assert "papilio.tasks.projection.broker" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)
