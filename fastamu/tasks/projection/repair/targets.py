from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from dishka import AsyncContainer

from fastamu.messaging.projections.contracts.base import (
    AbstractBatchProjection,
    Projection,
)
from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
)
from fastamu.messaging.projections.contracts.patch import (
    AbstractBatchPatchProjection,
)
from fastamu.messaging.projections.contracts.results import BulkItemResult
from fastamu.messaging.projections.repair.orchestration import RepairTarget
from fastamu.tasks.projection.delivery.register import Register

# The instance is untyped here on purpose: `resolve` pairs each call with
# the class it belongs to, so the match is checked where it is made.
type BatchCall = Callable[
    [Any, Sequence[int]], Awaitable[list[BulkItemResult]]
]

BATCH_CALLS: tuple[tuple[type, BatchCall], ...] = (
    (AbstractBatchProjection, AbstractBatchProjection.batch_project),
    (AbstractBatchPatchProjection, AbstractBatchPatchProjection.batch_project),
    (AbstractBatchUnProjection, AbstractBatchUnProjection.batch_unproject),
)


def resolve(
    register: Register,
    targets: Mapping[str, str],
) -> dict[str, tuple[type[Projection], BatchCall]]:
    """Check configured task-name pairs before anything runs."""
    by_name = {
        task.task_name: projection
        for projection, task in register.tasks.items()
    }
    bound: dict[str, tuple[type[Projection], BatchCall]] = {}
    for source, destination in targets.items():
        if source not in by_name or destination not in by_name:
            raise ValueError(
                f"Unknown repair mapping: {source} -> {destination}"
            )
        target = by_name[destination]
        call = next(
            (call for base, call in BATCH_CALLS if issubclass(target, base)),
            None,
        )
        if call is None:
            raise TypeError(f"Repair target must be a batch: {destination}")
        bound[source] = (target, call)
    return bound


def runners(
    targets: Mapping[str, tuple[type[Projection], BatchCall]],
    container: AsyncContainer,
) -> dict[str, RepairTarget]:
    """Wrap each target so repair runs it in its own scope, like a worker."""

    def runner(projection: type[Projection], call: BatchCall) -> RepairTarget:
        async def run(ids: Sequence[int]) -> list[BulkItemResult]:
            async with container() as scope:
                return await call(await scope.get(projection), list(ids))

        return run

    return {
        name: runner(projection, call)
        for name, (projection, call) in targets.items()
    }
