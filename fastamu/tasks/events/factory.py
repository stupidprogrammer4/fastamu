"""Build event transports when their lifecycle owner first requests them."""

from functools import lru_cache

from faststream.rabbit import (
    Channel,
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
)
from faststream.redis import RedisBroker

from fastamu.core.config import EventsConfig, get_settings


class BrokerFactory:
    @staticmethod
    def create(config: EventsConfig) -> RabbitBroker | RedisBroker:
        """Build the configured broker; its owner manages the lifecycle."""
        match config.broker:
            case "rabbitmq":
                return RabbitBroker(
                    config.url, default_channel=Channel(on_return_raises=True)
                )
            case "redis":
                return RedisBroker(config.url)
            case _:
                raise ValueError(
                    f"Unsupported event broker: {config.broker!r}"
                )


@lru_cache(maxsize=1)
def get_event_transport() -> tuple[
    RabbitBroker | RedisBroker, RabbitExchange | None
]:
    config = get_settings().tasks.events
    if config is None:
        raise RuntimeError("Events are disabled; configure tasks.events")
    broker = BrokerFactory.create(config)
    exchange = (
        RabbitExchange(config.exchange, type=ExchangeType.TOPIC, durable=True)
        if isinstance(broker, RabbitBroker)
        else None
    )
    return broker, exchange
