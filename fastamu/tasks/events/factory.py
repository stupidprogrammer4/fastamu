"""Select the FastStream transport without connecting to it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastamu.core.config import EventsConfig

if TYPE_CHECKING:
    from faststream.rabbit import RabbitBroker
    from faststream.redis import RedisBroker


class BrokerFactory:
    @staticmethod
    def create(config: EventsConfig) -> RabbitBroker | RedisBroker:
        """Build the configured broker; its owner manages the lifecycle."""
        match config.broker:
            case "rabbitmq":
                from faststream.rabbit import RabbitBroker

                return RabbitBroker(config.url)
            case "redis":
                from faststream.redis import RedisBroker

                return RedisBroker(config.url)
            case _:
                raise ValueError(
                    f"Unsupported event broker: {config.broker!r}"
                )
