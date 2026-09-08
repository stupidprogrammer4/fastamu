"""Sending projections does not register tasks or declare queues."""

from collections.abc import Sequence

from fastamu.common.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.tasks.projection.registry import registry


class ProjectionQueue[
    TProjection: AbstractProjection | AbstractFanoutProjection
]:
    async def queue(self, projection: type[TProjection], id: int) -> None:
        await registry.task(projection).kiq(id)


class BatchProjectionQueue[TProjection: AbstractBatchProjection]:
    async def queue(
        self, projection: type[TProjection], ids: Sequence[int]
    ) -> None:
        if not ids:
            return
        await registry.task(projection).kiq(list(dict.fromkeys(ids)))


class UnProjectionQueue[TProjection: AbstractUnProjection]:
    async def queue(self, projection: type[TProjection], id: int) -> None:
        await registry.task(projection).kiq(id)
