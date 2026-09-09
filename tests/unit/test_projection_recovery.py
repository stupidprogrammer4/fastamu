from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from taskiq import InMemoryBroker, TaskiqMessage

from fastamu.core.config import ProjectionConfig
from fastamu.tasks.projection.recovery import (
    ProjectionRecovery,
    publish_confirmed,
)
from fastamu.tasks.projection.scheduler import register_recovery


@pytest.fixture
def recovery():
    broker = InMemoryBroker()

    async def handler(id):
        pass

    broker.task(task_name="create", queue_name="products")(handler)
    return ProjectionRecovery(ProjectionConfig(url="amqp://localhost"), broker)


def test_failure_keeps_identity_input_error_and_attempts(recovery):
    message = TaskiqMessage(
        task_id="job-17",
        task_name="create",
        args=[17],
        kwargs={},
        labels={
            "queue_name": "products",
            "recovery_attempts": 100,
            "first_failed_at": 123.0,
        },
    )
    result = recovery.failure(
        recovery.broker.formatter.dumps(message).message,
        RuntimeError("Elasticsearch unavailable"),
    )
    assert result.message == message
    assert result.queue == "products"
    assert result.attempts == 101
    assert result.first_failed_at == 123.0
    assert "Elasticsearch unavailable" in result.error


def test_malformed_message_is_preserved_for_inspection(recovery):
    result = recovery.failure(b"not-json", ValueError("invalid payload"))
    assert result.message is None
    assert result.raw_message == "bm90LWpzb24="
    assert "invalid payload" in result.error


@pytest.mark.parametrize("deadline", ["nan", "inf", "-1", "invalid"])
def test_invalid_deadline_gets_finite_retry_window(recovery, deadline):
    message = TaskiqMessage(
        task_id="invalid-deadline",
        task_name="create",
        args=[17],
        kwargs={},
        labels={"projection_expires_at": deadline},
    )
    result = recovery.failure(
        recovery.broker.formatter.dumps(message).message,
        RuntimeError("unavailable"),
    )
    assert result.expires_at == result.failed_at + recovery.config.retry_ttl
    assert result.expired_at is None


def test_failed_and_expired_work_cannot_share_a_queue():
    with pytest.raises(ValueError, match="must be different"):
        ProjectionConfig(
            url="amqp://localhost",
            failure_queue="same",
            expired_queue="same",
        )


async def test_publish_requires_routing_and_confirmation():
    publish = AsyncMock(return_value=None)
    channel = SimpleNamespace(
        default_exchange=SimpleNamespace(publish=publish)
    )
    with pytest.raises(RuntimeError, match="did not confirm"):
        await publish_confirmed(channel, "products", b"payload")
    assert publish.call_args.kwargs["mandatory"] is True
    assert publish.call_args.args[0].delivery_mode == 2


def test_recovery_job_runs_every_five_minutes(recovery):
    register_recovery(recovery.broker, recovery.config)
    task = recovery.broker.find_task("fastamu.projection.recover")
    assert task.labels["schedule"] == [{"cron": "*/5 * * * *"}]
