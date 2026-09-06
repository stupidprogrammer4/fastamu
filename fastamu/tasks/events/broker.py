"""The configured event broker and its transport-level publish operation."""

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from faststream.redis import RedisBroker
from pydantic import BaseModel

from fastamu.core.config import get_settings
from fastamu.tasks.events.factory import BrokerFactory

event_cfg = get_settings().tasks.events
if event_cfg is None:
    raise RuntimeError("Events are disabled; configure tasks.events")
broker = BrokerFactory.create(event_cfg)
exchange = (
    RabbitExchange(
        event_cfg.exchange,
        type=ExchangeType.TOPIC,
        durable=True,
    )
    if isinstance(broker, RabbitBroker)
    else None
)


async def publish(subject: str, data: BaseModel) -> None:
    """Publish one persistent domain event on the configured transport."""
    body = data.model_dump(mode="json")
    if isinstance(broker, RabbitBroker):
        assert exchange is not None
        await broker.publish(
            body,
            exchange=exchange,
            routing_key=subject,
            persist=True,
        )
        return
    assert isinstance(broker, RedisBroker)
    await broker.publish(body, channel=subject)


def rabbit_exchange() -> RabbitExchange:
    """Return the configured RabbitMQ topic exchange for subscribers."""
    if exchange is None:
        raise RuntimeError(
            "RabbitMQ event exchange requested for another broker"
        )
    return exchange
