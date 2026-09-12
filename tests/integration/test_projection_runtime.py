import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from fastamu import scaffold

PROJECTIONS = """
from typing import ClassVar
from collections.abc import Sequence
from sqlalchemy import text
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.projections.contracts.delete import (
    AbstractUnProjection, AbstractBatchUnProjection,
)
from fastamu.messaging.projections.contracts.results import BulkItemResult

class DeleteProduct(AbstractUnProjection):
    queue_name: ClassVar[str] = "QUEUE_PRODUCTS"

    def __init__(self, unit: DBUnitOfWork) -> None:
        self.unit = unit

    async def _es_query(self, id: int) -> None:
        await self.unit.session.execute(
            text("INSERT INTO executions VALUES (:operation, :id)"),
            {"operation": type(self).__name__, "id": id},
        )
        await self.unit.commit()

class DeletePrice(DeleteProduct):
    pass

class DeleteVariant(DeleteProduct):
    queue_name: ClassVar[str] = "QUEUE_VARIANTS"

class DeleteBatch(AbstractBatchUnProjection):
    queue_name: ClassVar[str] = "QUEUE_PRODUCTS"

    def __init__(self, unit: DBUnitOfWork) -> None:
        self.unit = unit

    async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
        await self.unit.session.execute(
            text("INSERT INTO executions VALUES (:operation, :id)"),
            [{"operation": "DeleteBatch", "id": id} for id in ids],
        )
        await self.unit.commit()
        return [BulkItemResult(id=str(id), status=200) for id in ids]
"""

PROVIDERS = """
from dishka import Provider, Scope, provide_all
from .app.projections import (
    DeleteProduct, DeletePrice, DeleteVariant, DeleteBatch,
)

class ProjectionProvider(Provider):
    projections = provide_all(
        DeleteProduct, DeletePrice, DeleteVariant, DeleteBatch,
        scope=Scope.REQUEST,
    )
"""

PRODUCER = """
import asyncio
from fastamu.tasks.lifespan import task_lifespan
from fastamu.tasks.projection.broker import broker
from fastamu.tasks.projection.delivery.decorators import (
    unproject, batch_unproject,
)
from projection_probe.products.app.projections import (
    DeleteProduct, DeletePrice, DeleteVariant, DeleteBatch,
)

@unproject(DeleteProduct, lambda result: result)
async def product() -> int:
    return 42

@unproject(DeletePrice, lambda result: result)
async def price() -> int:
    return 43

@unproject(DeleteVariant, lambda result: result)
async def variant() -> int:
    return 44

@batch_unproject(DeleteBatch, lambda result: result)
async def batch() -> list[int]:
    return [45, 46]

async def main():
    async with task_lifespan():
        assert not broker.is_worker_process
        assert "projection_container" not in broker.state
        await product()
        await price()
        await variant()
        await batch()

asyncio.run(main())
"""


def test_real_rabbitmq_producer_and_separate_worker(tmp_path: Path) -> None:
    url = os.environ.get("FASTAMU_TEST_RABBIT_URL")
    if not url:
        pytest.skip("Set FASTAMU_TEST_RABBIT_URL to a disposable RabbitMQ")
    token = "fastamu_test_" + uuid4().hex
    app = tmp_path / "projection_probe" / "products"
    (app / "app").mkdir(parents=True)
    for folder in (app.parent, app, app / "app"):
        (folder / "__init__.py").touch()
    (app / "app" / "projections.py").write_text(
        PROJECTIONS.replace("QUEUE_PRODUCTS", token + ".products").replace(
            "QUEUE_VARIANTS", token + ".variants"
        )
    )
    (app / "providers.py").write_text(PROVIDERS)
    db_path = tmp_path / "executions.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE executions (operation TEXT, id INTEGER)")

    config = yaml.safe_load(scaffold.files("probe", "Probe")["config.yml"])
    config["app"]["modules"] = ["projection_probe"]
    config["db"]["dsn"] = f"sqlite+aiosqlite:///{db_path}"
    config["tasks"]["projection"] = {
        "url": url,
        "exchange": token,
        "prefetch": 4,
    }
    (tmp_path / "config.yml").write_text(yaml.safe_dump(config))
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    worker_log = tmp_path / "worker.log"
    with worker_log.open("w") as log:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "taskiq",
                "worker",
                "fastamu.tasks.projection.broker:broker",
                "--workers",
                "1",
                "--max-async-tasks",
                "4",
            ],
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            producer = subprocess.run(
                [sys.executable, "-c", PRODUCER],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert producer.returncode == 0, producer.stderr
            deadline = time.monotonic() + 30
            expected = {
                ("DeleteProduct", 42),
                ("DeletePrice", 43),
                ("DeleteVariant", 44),
                ("DeleteBatch", 45),
                ("DeleteBatch", 46),
            }
            rows = []
            while time.monotonic() < deadline:
                with sqlite3.connect(db_path) as db:
                    rows = db.execute(
                        "SELECT operation, id FROM executions"
                    ).fetchall()
                if len(rows) == len(expected) or worker.poll() is not None:
                    break
                time.sleep(0.1)
            assert set(rows) == expected, worker_log.read_text()
            assert len(rows) == len(expected)
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
