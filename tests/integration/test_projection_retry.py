import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import aio_pika
import orjson
import pytest
import yaml
from redis import Redis

from fastamu import scaffold

PROJECTIONS = """
import time
from typing import ClassVar
from sqlalchemy import text
from taskiq import TaskiqMessage
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.projections.contracts.delete import AbstractUnProjection
from fastamu.messaging.projections.contracts.policies import RetryPolicy

class Product(AbstractUnProjection):
    queue_name: ClassVar[str] = "QUEUE_PRODUCTS"
    retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
        max_attempts=3, delay=2,
    )

    def __init__(self, unit: DBUnitOfWork, message: TaskiqMessage) -> None:
        self.unit = unit
        self.message = message

    async def _es_query(self, id: int) -> None:
        await self.unit.session.execute(text(
            "INSERT INTO attempts VALUES (:operation, :task_id, :attempt, "
            ":queue, :time)"
        ), {
            "operation": type(self).__name__,
            "task_id": self.message.task_id,
            "attempt": int(self.message.labels.get("_retries", 0)),
            "queue": self.message.labels["queue_name"],
            "time": time.time(),
        })
        await self.unit.commit()
        if type(self).__name__ == "Variant" and self.message.labels.get(
            "_retries"
        ):
            return
        raise RuntimeError("projection probe failure")

class Variant(Product):
    queue_name: ClassVar[str] = "QUEUE_VARIANTS"
    retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
        max_attempts=4, delay=4,
    )

class Disabled(Product):
    retry_policy: ClassVar[RetryPolicy | None] = None
"""

PROVIDERS = """
from dishka import Provider, Scope, provide_all
from .app.projections import Product, Variant, Disabled

class Projections(Provider):
    projections = provide_all(Product, Variant, Disabled, scope=Scope.REQUEST)
"""

PRODUCER = """
import asyncio
from fastamu.tasks.lifespan import task_lifespan
from fastamu.tasks.projection.delivery.register import register
from retry_probe.products.app.projections import Product, Variant, Disabled

async def main():
    async with task_lifespan():
        for projection in (Product, Variant, Disabled):
            await register.get(projection).kiq(id=42)

asyncio.run(main())
"""


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_native_retry_with_rabbit_redis_and_separate_scheduler(
    tmp_path: Path,
) -> None:
    rabbit_url = os.environ.get("FASTAMU_TEST_RABBIT_URL")
    redis_url = os.environ.get("FASTAMU_TEST_REDIS_URL")
    if not rabbit_url or not redis_url:
        pytest.skip("Set disposable FASTAMU_TEST_RABBIT_URL and REDIS_URL")
    token = "fastamu_retry_" + uuid4().hex
    app = tmp_path / "retry_probe" / "products"
    (app / "app").mkdir(parents=True)
    for folder in (app.parent, app, app / "app"):
        (folder / "__init__.py").touch()
    (app / "app" / "projections.py").write_text(
        PROJECTIONS.replace("QUEUE_PRODUCTS", token + ".products").replace(
            "QUEUE_VARIANTS", token + ".variants"
        )
    )
    (app / "providers.py").write_text(PROVIDERS)
    db_path = tmp_path / "attempts.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE attempts (operation TEXT, task_id TEXT, "
            "attempt INTEGER, queue TEXT, time REAL)"
        )
    config = yaml.safe_load(scaffold.files("probe", "Probe")["config.yml"])
    config["app"]["modules"] = ["retry_probe"]
    config["db"]["dsn"] = f"sqlite+aiosqlite:///{db_path}"
    config["tasks"]["projection"] = {
        "url": rabbit_url,
        "exchange": token,
        "prefetch": 4,
        "retry": {"url": redis_url, "prefix": token},
    }
    (tmp_path / "config.yml").write_text(yaml.safe_dump(config))
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}

    def rows() -> list[tuple]:
        with sqlite3.connect(db_path) as db:
            return db.execute(
                "SELECT * FROM attempts ORDER BY time"
            ).fetchall()

    with ExitStack() as stack:
        redis = stack.enter_context(Redis.from_url(redis_url))

        def start(kind: str, target: str, *args: str) -> subprocess.Popen:
            log = stack.enter_context((tmp_path / f"{kind}.log").open("a"))
            process = subprocess.Popen(
                [sys.executable, "-m", "taskiq", kind, target, *args],
                cwd=tmp_path,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            stack.callback(stop, process)
            return process

        worker_args = (
            "worker",
            "fastamu.tasks.projection.broker:broker",
            "--workers",
            "1",
            "--max-async-tasks",
            "4",
        )
        worker = start(*worker_args)
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
        while time.monotonic() < deadline:
            if (
                len(rows()) == 3
                and len(list(redis.scan_iter(f"{token}:data:*"))) == 2
            ):
                break
            assert worker.poll() is None, (tmp_path / "worker.log").read_text()
            time.sleep(0.1)
        assert len(rows()) == 3, (tmp_path / "worker.log").read_text()
        assert len(list(redis.scan_iter(f"{token}:data:*"))) == 2
        # Initial messages executed before any scheduler was started.
        stop(worker)
        scheduler = start(
            "scheduler",
            "fastamu.tasks.projection.scheduler:scheduler",
            "--update-interval",
            "1",
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not list(redis.scan_iter(f"{token}:data:*")):
                break
            assert scheduler.poll() is None, (
                tmp_path / "scheduler.log"
            ).read_text()
            time.sleep(0.1)
        assert not list(redis.scan_iter(f"{token}:data:*"))

        async def check_actual_queues() -> None:
            connection = await aio_pika.connect(rabbit_url)
            async with connection:
                channel = await connection.channel()
                for suffix, operation in (
                    ("products", "Product"),
                    ("variants", "Variant"),
                ):
                    queue = await channel.get_queue(f"{token}.{suffix}")
                    message = await queue.get(timeout=5)
                    assert message is not None
                    payload = orjson.loads(message.body)
                    assert payload["task_name"].endswith(":" + operation)
                    assert "delay" not in payload["labels"]
                    await message.nack(requeue=True)

        asyncio.run(check_actual_queues())
        worker = start(*worker_args)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if len(rows()) >= 6:
                break
            assert worker.poll() is None, (tmp_path / "worker.log").read_text()
            time.sleep(0.1)
        # Wait beyond one more retry delay to detect a non-stopping policy.
        time.sleep(5)
        attempts = rows()
        assert len(attempts) == 6, (tmp_path / "worker.log").read_text()
        for operation, expected, delay in (
            ("Product", 3, 2),
            ("Variant", 2, 4),
            ("Disabled", 1, 0),
        ):
            executions = [row for row in attempts if row[0] == operation]
            assert len(executions) == expected
            assert len({row[1] for row in executions}) == 1
            assert [row[2] for row in executions] == list(range(expected))
            for previous, current in zip(executions, executions[1:]):
                assert current[4] - previous[4] >= delay
        assert not list(redis.scan_iter(f"{token}:data:*"))
