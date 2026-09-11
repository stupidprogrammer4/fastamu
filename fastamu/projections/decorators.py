"""Independent decorators matching each projection's input contract."""

from collections.abc import Callable, Sequence
from typing import Any

from fastamu.messaging.calls import Call, after_result
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.projections.definition import validate_projection
from fastamu.tasks.projection import publisher


def projection(
    target: type[AbstractProjection], *, id: Callable[[Call[Any]], int]
):
    """Publish one source ID after the wrapped call succeeds.

    Place outside @transactional for publication after its own commit.
    """
    validate_projection(target, AbstractProjection, id)

    async def send(call: Call[Any]) -> None:
        value = id(call)
        if type(value) is not int:
            raise TypeError("Projection ID must be an integer")
        await publisher.publish(target, value)

    return after_result(send)


def batch_projection(
    target: type[AbstractBatchProjection],
    *,
    ids: Callable[[Call[Any]], Sequence[int]],
):
    """Publish one batch after success; an empty batch sends nothing."""
    validate_projection(target, AbstractBatchProjection, ids)

    async def send(call: Call[Any]) -> None:
        values = ids(call)
        if isinstance(values, (str, bytes)) or not isinstance(
            values, Sequence
        ):
            raise TypeError("Batch projection requires a sequence of IDs")
        if any(type(value) is not int for value in values):
            raise TypeError("Batch projection IDs must be integers")
        if values:
            await publisher.publish(target, list(dict.fromkeys(values)))

    return after_result(send)


def fanout_projection(
    target: type[AbstractFanoutProjection],
    *,
    id: Callable[[Call[Any]], int],
):
    """Publish one source ID; the worker builds its multiple documents."""
    validate_projection(target, AbstractFanoutProjection, id)

    async def send(call: Call[Any]) -> None:
        value = id(call)
        if type(value) is not int:
            raise TypeError("Fanout projection ID must be an integer")
        await publisher.publish(target, value)

    return after_result(send)


def unprojection(
    target: type[AbstractUnProjection], *, id: Callable[[Call[Any]], int]
):
    """Publish one deletion ID after the wrapped call succeeds."""
    validate_projection(target, AbstractUnProjection, id)

    async def send(call: Call[Any]) -> None:
        value = id(call)
        if type(value) is not int:
            raise TypeError("UnProjection ID must be an integer")
        await publisher.publish(target, value)

    return after_result(send)
