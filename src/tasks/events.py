"""A tiny event bus over taskiq."""

import asyncio
from collections.abc import Callable
from typing import Any

from dishka.integrations.taskiq import FromDishka, inject

from src.common.bases.events import EventHandler, EventInput

# the shared event vocabulary (emitters and handlers meet on these names)
METAL_PRICE_UPDATED = "metal_price_updated"


class EventBus:
    """Holds the event -> handler-tasks registry and dispatches emitted events.

    A custom ``broker`` can be injected (mainly for tests that run a real worker
    against an isolated broker); when omitted, the app-wide broker is imported
    lazily on first registration so ``emit`` stays importable without it.
    """

    def __init__(self, broker: Any | None = None) -> None:
        self._broker = broker
        # event name -> the registered taskiq tasks (one per subscribed handler)
        self._handlers: dict[str, list[Any]] = {}

    def _resolve_broker(self) -> Any:
        broker = self._broker
        if broker is None:
            from src.tasks.broker import broker  # lazy — keeps `emit` importable without it
        return broker

    def on(self, event: str) -> Callable[[type], type]:
        """Subscribe a handler class to an event.

        The payload type is read off the handler's own ``EventHandler[X]`` header,
        so a handler that forgot to name one fails here, at import time, instead
        of on a worker holding a job it cannot parse.

        Args:
            event (str): The event name to handle.
        Returns:
            (Callable[[type], type]): Class decorator that registers the handler.
        """
        def decorator(handler_cls: type[EventHandler[Any]]) -> type:
            broker = self._resolve_broker()

            task_name = f"on_{event}_{handler_cls.__name__}".lower().replace(".", "_")
            input_cls = handler_cls.input_type()

            async def _task(payload: dict[str, Any], handler: Any) -> Any:
                result = await handler.handle(input_cls.model_validate(payload))
                return result

            _task.__name__ = task_name
            _task.__qualname__ = task_name
            _task.__annotations__ = {
                "payload": dict[str, Any],
                "handler": FromDishka[handler_cls],
                "return": Any,
            }

            registered = broker.task(task_name=task_name, queue_name=f"{task_name}_queue")(
                inject(_task, patch_module=True)
            )
            self._handlers.setdefault(event, []).append(registered)
            return handler_cls

        return decorator

    async def emit(self, event: str, data: EventInput) -> None:
        """Emit an event — each subscribed handler is dispatched as its own job.

        The payload crosses the broker as JSON and is validated back into the
        handler's declared input on the worker, so a handler receives a typed
        model rather than a raw dict.

        Args:
            event (str): The event name.
            data (EventInput): What happened — the payload the handlers declared.
        Returns:
            (None)
        """
        handlers = self._handlers.get(event, [])
        payload = data.model_dump(mode="json")
        await asyncio.gather(*(handler.kiq(payload) for handler in handlers))


event_bus = EventBus()
on = event_bus.on
emit = event_bus.emit
