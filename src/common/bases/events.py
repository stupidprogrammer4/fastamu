"""The contract between an event emitter and its handlers.

A handler declares the payload it accepts in its class header — `EventHandler[X]`
— and the bus reads it back off that declaration. So the payload type is written
once, at the only place that can be checked, instead of being repeated in the
subscription and again when the job rebuilds it on the worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar, get_args, get_origin

from pydantic import BaseModel


class EventInput(BaseModel):
    """The base every event payload derives from — a plain pydantic model, so it
    survives the round trip through the broker as JSON and is re-validated on the
    other side."""


TEvent = TypeVar("TEvent", bound=EventInput)


class EventHandler(ABC, Generic[TEvent]):
    """One reaction to one event::

        class WarmCache(EventHandler[PriceUpdated]):
            async def handle(self, data: PriceUpdated) -> None: ...
    """

    @classmethod
    def input_type(cls) -> type[EventInput]:
        """Read the input a handler was declared against, so the bus can rebuild
        a payload without being told the type twice.

        Returns:
            (type[EventInput]): The input named in the class header.
        Raises:
            TypeError: The handler subclassed `EventHandler` without naming its
                input — caught at registration, not on the worker.
        """
        for base in getattr(cls, "__orig_bases__", ()):
            if get_origin(base) is not EventHandler:
                continue
            args = get_args(base)
            if args and isinstance(args[0], type):
                if issubclass(args[0], EventInput):
                    return args[0]
        raise TypeError(
            f"{cls.__name__} must name its input, as EventHandler[SomeEventInput]"
        )

    @abstractmethod
    async def handle(self, data: TEvent) -> Any: ...
