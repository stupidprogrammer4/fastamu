"""Check with pyright: selectors must preserve decorated method signatures."""

import asyncio
from typing import Protocol, assert_type

from pydantic import BaseModel

from fastamu.infra.db.transaction import transactional
from fastamu.messaging.calls import Call
from fastamu.messaging.events.decorators import event
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.projections.decorators import (
    batch_projection,
    fanout_projection,
    projection,
    unprojection,
)


class Created(BaseModel):
    id: int


class Creator(Protocol):
    async def create(self, id: int, *, title: str = "") -> Created: ...


class Remove(AbstractUnProjection):
    async def _es_query(self, id: int) -> None:
        pass


class Single(AbstractProjection):
    async def _db_query(self, id):
        return None

    async def _es_query(self, document):
        pass


class Batch(AbstractBatchProjection):
    async def _db_query(self, ids):
        return []

    async def _es_query(self, documents):
        pass


class Fanout(AbstractFanoutProjection):
    async def _db_query(self, id):
        return []

    async def _es_query(self, documents):
        pass


def selected_id(call: Call[Created]) -> int:
    return call.result.id


class Service:
    @event("created", payload=lambda call: call.result)
    @projection(Single, id=lambda call: call.result.id)
    @batch_projection(Batch, ids=lambda call: [call.result.id])
    @fanout_projection(Fanout, id=lambda call: call.result.id)
    @unprojection(Remove, id=lambda call: call.result.id)
    @transactional
    async def create(self, id: int, *, title: str = "") -> Created:
        return Created(id=id)

    @unprojection(Remove, id=selected_id)
    async def selected(self, id: int) -> Created:
        return Created(id=id)


async def check_signature(service: Service) -> None:
    creator: Creator = service
    assert_type(await creator.create(1), Created)
    assert_type(asyncio.create_task(service.create(1)), asyncio.Task[Created])
    assert_type(await service.create(1, title="created"), Created)
    assert_type(await service.selected(id=2), Created)
