"""Publish one task argument: a source ID, a batch, or a deletion ID."""

from fastamu.core.config import get_settings
from fastamu.tasks.projection.registry import registry


async def publish(
    projection: type,
    argument: int | list[int],
    *,
    message_id: str | None = None,
) -> None:
    if isinstance(argument, list):
        if not argument:
            return
        argument = list(dict.fromkeys(argument))
    config = get_settings().tasks.projection
    if config is None:
        raise RuntimeError("CQRS is disabled")
    task = registry.task(projection)
    if message_id is None:
        await task.kiq(argument)
    else:
        await task.kicker().with_task_id(message_id).kiq(argument)
