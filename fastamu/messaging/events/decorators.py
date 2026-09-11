"""Declare domain events with a selector or explicitly inside a branch."""

import inspect
from collections.abc import Callable
from typing import Any

import orjson
from pydantic import BaseModel

from fastamu.messaging.calls import Call, after_result
from fastamu.tasks.events import publisher


async def emit(subject: str, data: BaseModel) -> None:
    """Publish immediately, without requiring or inspecting a transaction."""
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Event subject must not be empty")
    if not isinstance(data, BaseModel):
        raise TypeError("Event payload must be a Pydantic model")
    payload = orjson.loads(data.model_dump_json())
    await publisher.publish(subject, payload)


def event(subject: str, *, payload: Callable[[Call[Any]], BaseModel | None]):
    """Publish after the wrapped call succeeds; None skips publication.

    Works without SQL. Place outside @transactional to send after that call
    commits; a nested call may still be inside its parent transaction.
    """
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Event subject must not be empty")
    if inspect.iscoroutinefunction(payload) or inspect.iscoroutinefunction(
        getattr(payload, "__call__", None)
    ):
        raise TypeError("Event selectors must be synchronous")
    if not callable(payload):
        raise TypeError("Event payload selector must be callable")

    async def send(call: Call[Any]) -> None:
        data = payload(call)
        if data is not None:
            await emit(subject, data)

    return after_result(send)
