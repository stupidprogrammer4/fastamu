"""Configured broker used by native FastStream routers and worker startup."""

from faststream.rabbit import RabbitExchange

from fastamu.tasks.events.factory import get_event_transport

broker, exchange = get_event_transport()


def rabbit_exchange() -> RabbitExchange:
    """Return the configured RabbitMQ topic exchange for subscribers."""
    if exchange is None:
        raise RuntimeError(
            "RabbitMQ event exchange requested for another broker"
        )
    return exchange
