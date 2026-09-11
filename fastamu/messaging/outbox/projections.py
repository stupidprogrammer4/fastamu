from collections.abc import Sequence
from uuid import UUID

import orjson

from fastamu.core.config import get_settings
from fastamu.infra.db.outbox.writer import append, require_transaction
from fastamu.infra.db.transaction import transaction
from fastamu.messaging.outbox.decorators import after_write
from fastamu.messaging.outbox.message import OutboxMessage
from fastamu.projections import definition
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.projections.definition import validate_projection


def projection_name(target: type) -> str:
    name = target.__dict__.get("outbox_name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ValueError("Projection must declare a stable outbox_name")
    matches = [
        cls
        for cls in definition.definitions.values()
        if cls.__dict__.get("outbox_name") == name
    ]
    if len(matches) != 1 or matches[0] is not target:
        raise ValueError(
            f"Outbox projection name is unregistered or duplicated: {name}"
        )
    return name


async def _record(target, argument) -> UUID:
    if get_settings().tasks.projection is None:
        raise RuntimeError("CQRS is disabled")
    return await append(
        OutboxMessage(
            kind="projection",
            target=projection_name(target),
            payload=orjson.dumps({"argument": argument}),
        )
    )


async def record_projection(target, *, id: int) -> UUID:
    require_transaction()
    async with transaction():
        if not issubclass(
            target,
            (
                AbstractProjection,
                AbstractFanoutProjection,
                AbstractUnProjection,
            ),
        ):
            raise TypeError("Single, fanout or deletion projection required")
        if type(id) is not int:
            raise TypeError("Projection ID must be an integer")
        return await _record(target, id)


async def record_batch_projection(
    target, *, ids: Sequence[int]
) -> UUID | None:
    require_transaction()
    async with transaction():
        if not issubclass(target, AbstractBatchProjection):
            raise TypeError("Batch projection required")
        if (
            isinstance(ids, (str, bytes))
            or not isinstance(ids, Sequence)
            or any(type(value) is not int for value in ids)
        ):
            raise TypeError(
                "Batch projection requires a sequence of integer IDs"
            )
        if not ids:
            return None
        return await _record(target, list(dict.fromkeys(ids)))


def projection(target, *, id):
    validate_projection(target, AbstractProjection, id)

    async def record(call):
        await record_projection(target, id=id(call))

    return after_write(record)


def batch_projection(target, *, ids):
    validate_projection(target, AbstractBatchProjection, ids)

    async def record(call):
        await record_batch_projection(target, ids=ids(call))

    return after_write(record)


def fanout_projection(target, *, id):
    validate_projection(target, AbstractFanoutProjection, id)

    async def record(call):
        await record_projection(target, id=id(call))

    return after_write(record)


def unprojection(target, *, id):
    validate_projection(target, AbstractUnProjection, id)

    async def record(call):
        await record_projection(target, id=id(call))

    return after_write(record)
