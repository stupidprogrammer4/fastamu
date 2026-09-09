"""Register recovery without coupling scheduler and projection lifecycles."""

from taskiq import AsyncBroker

from fastamu.core.config import ProjectionConfig
from fastamu.tasks.projection.recovery import ProjectionRecovery


def register_recovery(broker: AsyncBroker, config: ProjectionConfig) -> None:
    @broker.task(
        task_name="fastamu.projection.recover",
        schedule=[{"cron": config.recovery_cron}],
    )
    async def recover() -> int:
        # Discovery is synchronous; the recovery service owns its short-lived
        # RabbitMQ connection, not another broker's startup/shutdown.
        from fastamu.tasks.projection.worker import get_broker

        projection_broker = get_broker()
        recovery = ProjectionRecovery(config, projection_broker)
        return await recovery.replay()
