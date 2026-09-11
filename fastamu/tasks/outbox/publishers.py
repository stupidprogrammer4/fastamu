"""Resolve only registered destinations; transport imports are optional."""

from importlib import import_module

import orjson

from fastamu.messaging.outbox.message import OutboxMessage
from fastamu.projections import definition


async def publish(message: OutboxMessage) -> None:
    data = orjson.loads(message.payload)
    if message.kind == "event":
        publisher = import_module("fastamu.tasks.events.publisher")
        await publisher.publish(
            message.target,
            data,
            message_id=str(message.id),
            require_confirm=True,
        )
        return
    matches = [
        cls
        for cls in definition.definitions.values()
        if cls.__dict__.get("outbox_name") == message.target
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Unknown or duplicated outbox projection: {message.target}"
        )
    publisher = import_module("fastamu.tasks.projection.publisher")
    await publisher.publish(
        matches[0], data["argument"], message_id=str(message.id)
    )
