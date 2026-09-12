import os
import sqlite3
import subprocess
import sys
import time
from contextlib import ExitStack
from uuid import uuid4

import pytest
import redis
import yaml

from fastamu import scaffold
from tests.integration.test_projection_retry import stop

PROJECTIONS = """
from collections.abc import Sequence
from typing import ClassVar
from sqlalchemy import text
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.projections.contracts.delete import (
    AbstractUnProjection, AbstractBatchUnProjection,
)
from fastamu.messaging.projections.contracts.results import BulkItemResult

class Product(AbstractUnProjection):
    queue_name: ClassVar[str] = "PRODUCT_QUEUE"
    def __init__(self, unit: DBUnitOfWork) -> None:
        self.unit = unit
    async def _es_query(self, id: int) -> None:
        await self.unit.session.execute(
            text("INSERT INTO rolled_back VALUES (:id)"), {"id": id},
        )
        raise ValueError("terminal failure")

class Variant(Product):
    queue_name: ClassVar[str] = "VARIANT_QUEUE"

class Products(AbstractBatchUnProjection):
    queue_name: ClassVar[str] = "PRODUCT_QUEUE"
    def __init__(self, unit: DBUnitOfWork) -> None:
        self.unit = unit
    async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
        await self.unit.session.execute(
            text("INSERT INTO repaired VALUES (:operation, :id)"),
            [{"operation": type(self).__name__, "id": id} for id in ids],
        )
        await self.unit.commit()
        return [BulkItemResult(id=str(id), status=200) for id in ids]

class Variants(Products):
    queue_name: ClassVar[str] = "VARIANT_QUEUE"
"""

PROVIDERS = """
from dishka import Provider, Scope, provide_all
from .app.projections import Product, Variant, Products, Variants
class Projections(Provider):
    projections = provide_all(
        Product, Variant, Products, Variants, scope=Scope.REQUEST,
    )
"""

PRODUCER = """
import asyncio
from fastamu.tasks.lifespan import task_lifespan
from fastamu.tasks.projection.delivery.register import register
from repair_probe.products.app.projections import Product, Variant
async def main():
    async with task_lifespan():
        await register.get(Product).kiq(id=7)
        await register.get(Product).kiq(id=8)
        await register.get(Variant).kiq(id=9)
asyncio.run(main())
"""


def test_real_scheduler_repairs_without_retry_redis(tmp_path) -> None:
    url = os.environ.get("FASTAMU_TEST_RABBIT_URL")
    redis_url = os.environ.get("FASTAMU_TEST_REDIS_URL")
    if not url or not redis_url:
        pytest.skip("Set disposable FASTAMU_TEST_RABBIT_URL and REDIS_URL")
    token = "fastamu_repair_" + uuid4().hex
    app = tmp_path / "repair_probe" / "products"
    (app / "app").mkdir(parents=True)
    for folder in (app.parent, app, app / "app"):
        (folder / "__init__.py").touch()
    (app / "app" / "projections.py").write_text(
        PROJECTIONS.replace("PRODUCT_QUEUE", token + ".products").replace(
            "VARIANT_QUEUE", token + ".variants"
        )
    )
    (app / "providers.py").write_text(PROVIDERS)
    db_path = tmp_path / "failures.db"
    with sqlite3.connect(db_path) as database:
        database.execute("CREATE TABLE repaired (operation TEXT, id INTEGER)")
        database.execute("CREATE TABLE rolled_back (id INTEGER)")
    config = yaml.safe_load(scaffold.files("probe", "Probe")["config.yml"])
    config["app"]["modules"] = ["repair_probe"]
    config["db"]["dsn"] = f"sqlite+aiosqlite:///{db_path}"
    config["redis"]["url"] = redis_url
    prefix = "repair_probe.products.app.projections:"
    config["tasks"]["projection"] = {
        "url": url,
        "exchange": token,
        "prefetch": 4,
        "repair": {
            "interval": 1,
            "batch_size": 1000,
            "prefix": token,
            "targets": {
                prefix + "Product": prefix + "Products",
                prefix + "Variant": prefix + "Variants",
            },
        },
    }
    (tmp_path / "config.yml").write_text(yaml.safe_dump(config))
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    with ExitStack() as stack:
        for kind, target, args in (
            ("worker", "broker:broker", ["--workers", "1"]),
            ("scheduler", "scheduler:scheduler", ["--update-interval", "1"]),
        ):
            log = stack.enter_context((tmp_path / f"{kind}.log").open("w"))
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "taskiq",
                    kind,
                    "fastamu.tasks.projection." + target,
                    *args,
                ],
                cwd=tmp_path,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            stack.callback(stop, process)
        producer = subprocess.run(
            [sys.executable, "-c", PRODUCER],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert producer.returncode == 0, producer.stderr
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        stack.callback(client.close)
        queues = [f"{token}:{prefix}{name}" for name in ("Product", "Variant")]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with sqlite3.connect(db_path) as database:
                repaired = database.execute(
                    "SELECT * FROM repaired"
                ).fetchall()
            pending = sum(client.llen(queue) for queue in queues)
            if len(repaired) == 3 and pending == 0:
                break
            time.sleep(0.1)
        logs = "\n".join(
            (tmp_path / f"{kind}.log").read_text()
            for kind in ("worker", "scheduler")
        )
        assert sorted(repaired) == [
            ("Products", 7),
            ("Products", 8),
            ("Variants", 9),
        ], logs
        assert pending == 0, logs
        with sqlite3.connect(db_path) as database:
            assert (
                database.execute("SELECT * FROM rolled_back").fetchall() == []
            )
