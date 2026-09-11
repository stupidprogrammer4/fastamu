import inspect
from collections.abc import Callable
from typing import Any
from uuid import UUID

import orjson
from pydantic import BaseModel

from fastamu.core.config import get_settings
from fastamu.infra.db.outbox.writer import append, require_transaction
from fastamu.infra.db.transaction import transaction
from fastamu.messaging.calls import Call
from fastamu.messaging.outbox.decorators import after_write
from fastamu.messaging.outbox.message import OutboxMessage


async def record_event(subject: str, data: BaseModel) -> UUID:
    require_transaction()
    async with transaction():
        config = get_settings().tasks.events
        if config is None or config.broker != "rabbitmq":
            raise RuntimeError("Durable outbox events require RabbitMQ")
        if not isinstance(data, BaseModel):
            raise TypeError("Event payload must be a Pydantic model")
        return await append(
            OutboxMessage(
                kind="event",
                target=subject,
                payload=orjson.dumps(data.model_dump(mode="json")),
            )
        )


def event(subject: str, *, payload: Callable[[Call[Any]], BaseModel | None]):
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Event subject must not be empty")
    if (
        not callable(payload)
        or inspect.iscoroutinefunction(payload)
        or inspect.iscoroutinefunction(getattr(payload, "__call__", None))
    ):
        raise TypeError("Event selector must be synchronous and callable")

    async def record(call):
        data = payload(call)
        if data is not None:
            await record_event(subject, data)

    return after_write(record)
