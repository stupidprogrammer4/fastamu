"""Projection definitions; registration does not load task transports."""

import inspect
from collections.abc import Callable
from typing import ClassVar

from fastamu.messaging.retry import RetryPolicy

definitions: dict[str, type] = {}


class ProjectionDefinition:
    queue_name: ClassVar[str | None] = None
    outbox_name: ClassVar[str | None] = None
    retry_policy: ClassVar[RetryPolicy | None] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.queue_name is None:
            return
        if not cls.queue_name.strip():
            raise ValueError("Projection queue_name must not be empty")
        name = f"{cls.__module__}.{cls.__qualname__}"
        existing = definitions.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(f"Duplicate projection task: {name}")
        definitions[name] = cls


def validate_projection(target: type, base: type, selector: Callable) -> None:
    if not isinstance(target, type) or not issubclass(target, base):
        raise TypeError(f"Expected a {base.__name__} subclass")
    if inspect.isabstract(target):
        raise TypeError("Expected a concrete projection class")
    if not callable(selector):
        raise TypeError("Projection selector must be callable")
    if inspect.iscoroutinefunction(selector) or inspect.iscoroutinefunction(
        getattr(selector, "__call__", None)
    ):
        raise TypeError("Projection selectors must be synchronous")
