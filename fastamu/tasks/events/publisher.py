"""Immediate event publication using the lifecycle-managed transport."""

from typing import Any

from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic

from fastamu.tasks.events.factory import get_event_transport


async def publish(
    subject: str,
    data: dict,
    *,
    message_id: str | None = None,
    require_confirm: bool = False,
) -> None:
    broker, exchange = get_event_transport()
    if isinstance(broker, RabbitBroker):
        assert exchange is not None
        options: dict[str, Any] = (
            {"message_id": message_id} if message_id is not None else {}
        )
        confirmation = await broker.publish(
            data,
            exchange=exchange,
            routing_key=subject,
            persist=True,
            **options,
        )
        if require_confirm and not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("RabbitMQ did not confirm outbox publication")
    else:
        if require_confirm:
            raise RuntimeError("Durable outbox events require RabbitMQ")
        await broker.publish(data, channel=subject)
