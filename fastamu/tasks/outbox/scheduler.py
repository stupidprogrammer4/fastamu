"""Recovery is a regular interval job on the existing Taskiq scheduler."""

from datetime import timedelta
from importlib import import_module
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from taskiq import AsyncBroker

from fastamu.core.config import get_settings
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.outbox.repository import OutboxRepository
from fastamu.tasks.outbox.relay import OutboxRelay


@inject(patch_module=True)
async def recover(db: FromDishka[DBConnection]) -> int:
    config = get_settings().tasks.outbox
    if config is None or not config.polling:
        return 0
    batches = await OutboxRepository(db).plan_batches(
        batch_size=config.batch_size,
        max_batches=config.max_parallel_batches,
        lease_seconds=config.batch_lease_seconds,
    )
    broker = import_module("fastamu.tasks.schedulers.broker").broker
    task = broker.find_task("fastamu.outbox.publish_batch")
    if task is None:
        raise RuntimeError("Outbox batch task is not registered")
    for batch in batches:
        await task.kiq(str(batch.id))
    return len(batches)


@inject(patch_module=True)
async def publish_batch(batch_id: str, db: FromDishka[DBConnection]) -> int:
    config = get_settings().tasks.outbox
    if config is None or not config.polling:
        return 0
    return await OutboxRelay(OutboxRepository(db), config).run_batch(
        UUID(batch_id)
    )


def register(broker: AsyncBroker) -> None:
    config = get_settings().tasks.outbox
    if config is None or not config.polling:
        return
    if broker.find_task("fastamu.outbox.recover") is None:
        broker.task(
            task_name="fastamu.outbox.publish_batch",
            queue_name="outbox_queue",
            retry_on_error=False,
        )(publish_batch)
        broker.task(
            task_name="fastamu.outbox.recover",
            queue_name="outbox_queue",
            retry_on_error=False,
            schedule=[
                {
                    "interval": timedelta(seconds=config.poll_interval),
                    "schedule_id": "fastamu.outbox.recover",
                }
            ],
        )(recover)
