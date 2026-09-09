from unittest.mock import AsyncMock

import pytest

from fastamu.common.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
)
from fastamu.common.projections.convertor import Convertor
from fastamu.common.projections.errors import ProjectionSourceMissing


class StringConvertor(Convertor[int, str]):
    def convert(self, model: int) -> str:
        if model < 0:
            raise ValueError("Invalid source model")
        return str(model)


class Projection(AbstractProjection[int, str]):
    def __init__(self, models):
        super().__init__(StringConvertor())
        self.read = AsyncMock(return_value=models)
        self.write = AsyncMock()

    async def _db_query(self, ids):
        return await self.read(ids)

    async def _es_query(self, documents):
        await self.write(documents)


class BatchProjection(AbstractBatchProjection[int, str]):
    def __init__(self, models):
        super().__init__(StringConvertor())
        self.read = AsyncMock(return_value=models)
        self.write = AsyncMock()

    async def _db_query(self, ids):
        return await self.read(ids)

    async def _es_query(self, documents):
        await self.write(documents)


class FanoutProjection(AbstractFanoutProjection[int, str]):
    def __init__(self, models):
        super().__init__(StringConvertor())
        self.read = AsyncMock(return_value=models)
        self.write = AsyncMock()

    async def _db_query(self, id):
        return await self.read(id)

    async def _es_query(self, documents):
        await self.write(documents)


async def test_batch_reads_and_writes_once_preserving_id_order():
    projection = BatchProjection([3, 1])
    await projection.batch_project([3, 1, 3])
    projection.read.assert_awaited_once_with([3, 1])
    projection.write.assert_awaited_once_with(["3", "1"])


async def test_single_reads_and_writes_one_item():
    projection = Projection(7)
    await projection.project(7)
    projection.read.assert_awaited_once_with(7)
    projection.write.assert_awaited_once_with("7")


async def test_fanout_reads_one_identity_and_writes_many_documents():
    projection = FanoutProjection([3, 1])
    await projection.project(7)
    projection.read.assert_awaited_once_with(7)
    projection.write.assert_awaited_once_with(["3", "1"])


async def test_empty_input_does_no_io():
    projection = BatchProjection([])
    await projection.batch_project([])
    projection.read.assert_not_awaited()
    projection.write.assert_not_awaited()


async def test_a_source_not_yet_visible_is_refused_rather_than_skipped():
    projection = Projection(None)
    with pytest.raises(ProjectionSourceMissing):
        await projection.project(7)
    projection.write.assert_not_awaited()


async def test_conversion_failure_does_not_partially_write():
    projection = BatchProjection([1, -1])
    with pytest.raises(ValueError, match="Invalid source"):
        await projection.batch_project([1, 2])
    projection.write.assert_not_awaited()


@pytest.mark.parametrize("stage", ["read", "write"])
async def test_query_errors_propagate(stage):
    projection = Projection(1)
    getattr(projection, stage).side_effect = RuntimeError("Query failed")
    with pytest.raises(RuntimeError, match="Query failed"):
        await projection.project(1)
    if stage == "read":
        projection.write.assert_not_awaited()


async def test_falsey_source_model_is_converted():
    projection = Projection(0)
    await projection.project(0)
    projection.write.assert_awaited_once_with("0")


async def test_a_batch_seeing_no_source_is_refused_rather_than_skipped():
    projection = BatchProjection([])
    with pytest.raises(ProjectionSourceMissing):
        await projection.batch_project([7])
    projection.write.assert_not_awaited()


async def test_batch_does_not_silently_drop_missing_sources():
    projection = BatchProjection([1])
    with pytest.raises(ProjectionSourceMissing):
        await projection.batch_project([1, 2])
    projection.write.assert_not_awaited()


async def test_batch_deduplicates_before_checking_coverage():
    projection = BatchProjection([1, 2])
    await projection.batch_project([1, 2, 1])
    projection.write.assert_awaited_once_with(["1", "2"])
