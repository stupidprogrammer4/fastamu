"""Sending projections does not register tasks or declare queues."""

import time
from collections.abc import Sequence

from fastamu.common.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.core.config import get_settings
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.tasks.projection.registry import registry


async def _publish(projection: type, argument: int | list[int]) -> None:
    try:
        config = get_settings().tasks.projection
        if config is None:
            raise RuntimeError("CQRS is disabled")
        expires_at = time.time() + config.retry_ttl
        ticket = await DBUnitOfWork.stage_projection(
            projection,
            argument if isinstance(argument, list) else [argument],
            expires_at,
        )
        labels = {"projection_expires_at": str(expires_at)}
        if ticket is not None:
            labels["projection_version"] = ticket.model_dump_json()
        await (
            registry.task(projection)
            .kicker()
            .with_labels(**labels)
            .kiq(argument)
        )
    except BaseException:
        DBUnitOfWork.mark_rollback_only()
        raise


class ProjectionQueue[
    TProjection: AbstractProjection | AbstractFanoutProjection
]:
    async def queue(self, projection: type[TProjection], id: int) -> None:
        await _publish(projection, id)


class BatchProjectionQueue[TProjection: AbstractBatchProjection]:
    async def queue(
        self, projection: type[TProjection], ids: Sequence[int]
    ) -> None:
        if not ids:
            return
        await _publish(projection, list(dict.fromkeys(ids)))


class UnProjectionQueue[TProjection: AbstractUnProjection]:
    async def queue(self, projection: type[TProjection], id: int) -> None:
        await _publish(projection, id)
