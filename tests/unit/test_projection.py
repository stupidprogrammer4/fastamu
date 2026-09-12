import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

import pytest
from elasticsearch.dsl import AsyncDocument, M
from pydantic import BaseModel

from fastamu.messaging.projections.contracts.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
)
from fastamu.messaging.projections.contracts.convertor import AbstractConvertor
from fastamu.messaging.projections.contracts.delete import (
    AbstractBatchUnProjection,
    AbstractUnProjection,
)
from fastamu.messaging.projections.contracts.patch import (
    AbstractBatchPatchProjection,
    AbstractPatchProjection,
)
from fastamu.messaging.projections.contracts.results import BulkItemResult


class Product(BaseModel):
    id: int
    title: str


class ProductDocument(AsyncDocument):
    title: M[str]


class ProductProjection(AbstractProjection[Product, ProductDocument]):
    def __init__(
        self,
        read: Callable[[int], Awaitable[Product]],
        convert: Callable[[Product], ProductDocument],
        write: Callable[[ProductDocument], Awaitable[None]],
    ) -> None:
        self.read = read
        self.convert = convert
        self.write = write

    async def _db_query(self, id: int) -> Product:
        return await self.read(id)

    def _convert(self, model: Product) -> ProductDocument:
        return self.convert(model)

    async def _es_query(self, document: ProductDocument) -> None:
        await self.write(document)


def product_document(model: Product) -> ProductDocument:
    document = ProductDocument(title=model.title)
    document.meta.id = str(model.id)
    return document


class ProductConvertor(AbstractConvertor[Product, ProductDocument]):
    def convert(self, model: Product) -> ProductDocument:
        return product_document(model)


async def test_projection_rebuilds_from_the_current_source() -> None:
    source = {7: Product(id=7, title="before")}
    written: list[ProductDocument] = []

    async def read(id: int) -> Product:
        return source[id]

    async def write(document: ProductDocument) -> None:
        written.append(document)

    projection = ProductProjection(read, product_document, write)
    assert await projection.project(7) is None
    source[7] = Product(id=7, title="after")
    await projection.project(7)

    assert [doc.to_dict() for doc in written] == [
        {"title": "before"},
        {"title": "after"},
    ]
    assert [doc.meta.id for doc in written] == ["7", "7"]


@pytest.mark.parametrize("failed_stage", ["read", "convert", "write"])
async def test_failure_stops_execution_without_retry(
    failed_stage: str,
) -> None:
    failure = LookupError("source missing")
    calls: list[str] = []

    def record(stage: str) -> None:
        calls.append(stage)
        if stage == failed_stage:
            raise failure

    async def read(id: int) -> Product:
        record("read")
        return Product(id=id, title="product")

    def convert(model: Product) -> ProductDocument:
        record("convert")
        return product_document(model)

    async def write(document: ProductDocument) -> None:
        record("write")

    projection = ProductProjection(read, convert, write)
    with pytest.raises(LookupError) as caught:
        await projection.project(7)

    assert caught.value is failure
    stages = ["read", "convert", "write"]
    assert calls == stages[: stages.index(failed_stage) + 1]


@pytest.mark.parametrize("cancel_during_read", [True, False])
async def test_cancellation_propagates_without_continuing(
    cancel_during_read: bool,
) -> None:
    started = asyncio.Event()
    calls: list[str] = []

    async def pause() -> None:
        started.set()
        await asyncio.Event().wait()

    async def read(id: int) -> Product:
        calls.append("read")
        if cancel_during_read:
            await pause()
        return Product(id=id, title="product")

    def convert(model: Product) -> ProductDocument:
        calls.append("convert")
        return product_document(model)

    async def write(document: ProductDocument) -> None:
        calls.append("write")
        await pause()

    projection = ProductProjection(read, convert, write)
    task = asyncio.create_task(projection.project(7))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls == (
        ["read"] if cancel_during_read else ["read", "convert", "write"]
    )


class ProductPatch(BaseModel):
    title: str | None = None
    active: bool = True


class ProductPatchProjection(
    AbstractPatchProjection[ProductPatch, ProductPatch]
):
    def __init__(self, source: ProductPatch) -> None:
        self.source = source
        self.writes: list[tuple[int, ProductPatch]] = []

    async def _db_query(self, id: int) -> ProductPatch:
        return self.source

    def _convert(self, model: ProductPatch) -> ProductPatch:
        return model.model_copy()

    async def _es_query(self, id: int, patch: ProductPatch) -> None:
        self.writes.append((id, patch))


class ProductBatchProjection(
    AbstractBatchProjection[Product, ProductDocument]
):
    def __init__(
        self,
        source: Mapping[int, Product],
        results: list[BulkItemResult],
    ) -> None:
        self.source = source
        self.results = results
        self.reads: list[tuple[int, ...]] = []
        self.writes: list[tuple[ProductDocument, ...]] = []

    async def _db_query(self, ids: Sequence[int]) -> Sequence[Product]:
        self.reads.append(tuple(ids))
        return [self.source[id] for id in ids]

    def _convert(self, model: Product) -> ProductDocument:
        return product_document(model)

    async def _es_query(
        self, documents: Sequence[ProductDocument]
    ) -> list[BulkItemResult]:
        self.writes.append(tuple(documents))
        return self.results


class ProductFanoutProjection(
    AbstractFanoutProjection[Product, ProductDocument]
):
    def __init__(
        self, source: Sequence[Product], results: list[BulkItemResult]
    ) -> None:
        self.source = source
        self.results = results
        self.reads: list[int] = []
        self.writes: list[tuple[ProductDocument, ...]] = []

    async def _db_query(self, id: int) -> Sequence[Product]:
        self.reads.append(id)
        return self.source

    def _convert(self, model: Product) -> ProductDocument:
        return product_document(model)

    async def _es_query(
        self, documents: Sequence[ProductDocument]
    ) -> list[BulkItemResult]:
        self.writes.append(tuple(documents))
        return self.results


class ProductBatchPatchProjection(
    AbstractBatchPatchProjection[ProductPatch, ProductPatch]
):
    def __init__(
        self,
        source: Mapping[int, ProductPatch],
        results: list[BulkItemResult],
    ) -> None:
        self.source = source
        self.results = results
        self.reads: list[tuple[int, ...]] = []
        self.writes: list[dict[int, ProductPatch]] = []

    async def _db_query(
        self, ids: Sequence[int]
    ) -> Mapping[int, ProductPatch]:
        self.reads.append(tuple(ids))
        return self.source

    def _convert(self, model: ProductPatch) -> ProductPatch:
        return model.model_copy()

    async def _es_query(
        self, patches: Mapping[int, ProductPatch]
    ) -> list[BulkItemResult]:
        self.writes.append(dict(patches))
        return self.results


class ProductUnProjection(AbstractUnProjection):
    def __init__(self) -> None:
        self.deleted: list[int] = []

    async def _es_query(self, id: int) -> None:
        self.deleted.append(id)


class ProductBatchUnProjection(AbstractBatchUnProjection):
    def __init__(self, results: list[BulkItemResult]) -> None:
        self.results = results
        self.writes: list[tuple[int, ...]] = []

    async def _es_query(self, ids: Sequence[int]) -> list[BulkItemResult]:
        self.writes.append(tuple(ids))
        return self.results


@pytest.fixture
def bulk_results() -> list[BulkItemResult]:
    return [
        BulkItemResult(id="7", status=200),
        BulkItemResult(
            id="3",
            status=500,
            error={
                "type": "mapper_parsing_exception",
                "reason": "failed to parse field",
            },
        ),
    ]


@pytest.mark.parametrize(
    "source,expected_fields",
    [
        (ProductPatch(), {}),
        (ProductPatch(title=None), {"title": None}),
        (ProductPatch(active=False), {"active": False}),
        (ProductPatch(title=""), {"title": ""}),
    ],
)
async def test_patch_preserves_explicit_fields(
    source: ProductPatch,
    expected_fields: dict[str, str | bool | None],
) -> None:
    projection = ProductPatchProjection(source)
    await projection.project(7)
    id, patch = projection.writes[0]
    assert id == 7
    assert patch.model_fields_set == source.model_fields_set
    assert patch.model_dump(exclude_unset=True) == expected_fields


async def test_batch_performs_one_group_write_and_keeps_partial_results(
    bulk_results: list[BulkItemResult],
) -> None:
    source = {id: Product(id=id, title=str(id)) for id in (3, 7)}
    projection = ProductBatchProjection(source, bulk_results)
    ids = [7, 3]

    result = await projection.batch_project(ids)

    assert projection.reads == [(7, 3)]
    assert len(projection.writes) == 1
    assert [doc.meta.id for doc in projection.writes[0]] == ["7", "3"]
    assert result is bulk_results
    assert result[0].succeeded
    assert not result[1].succeeded
    assert result[1].status == 500
    assert ids == [7, 3]


async def test_fanout_reads_one_source_and_writes_multiple_documents(
    bulk_results: list[BulkItemResult],
) -> None:
    projection = ProductFanoutProjection(
        [Product(id=7, title="first"), Product(id=3, title="second")],
        bulk_results,
    )
    result = await projection.project(100)
    assert projection.reads == [100]
    assert len(projection.writes) == 1
    assert [doc.meta.id for doc in projection.writes[0]] == ["7", "3"]
    assert result is bulk_results


async def test_batch_patch_keeps_target_association_when_query_reorders(
    bulk_results: list[BulkItemResult],
) -> None:
    projection = ProductBatchPatchProjection(
        {3: ProductPatch(title=None), 7: ProductPatch(active=False)},
        bulk_results,
    )
    result = await projection.batch_project([7, 3])
    assert projection.reads == [(7, 3)]
    assert len(projection.writes) == 1
    patches = projection.writes[0]
    assert patches[3].model_dump(exclude_unset=True) == {"title": None}
    assert patches[7].model_dump(exclude_unset=True) == {"active": False}
    assert result is bulk_results


async def test_deletion_needs_no_source_or_converter() -> None:
    projection = ProductUnProjection()
    await projection.unproject(42)
    assert projection.deleted == [42]


async def test_batch_deletion_uses_one_write_without_mutating_input(
    bulk_results: list[BulkItemResult],
) -> None:
    projection = ProductBatchUnProjection(bulk_results)
    ids = [7, 3, 7]
    result = await projection.batch_unproject(ids)
    assert projection.writes == [(7, 3, 7)]
    assert ids == [7, 3, 7]
    assert result is bulk_results


async def test_empty_batches_do_no_io() -> None:
    full = ProductBatchProjection({}, [])
    patches = ProductBatchPatchProjection({}, [])
    deletion = ProductBatchUnProjection([])
    assert await full.batch_project([]) == []
    assert await patches.batch_project([]) == []
    assert await deletion.batch_unproject([]) == []
    assert full.reads == full.writes == []
    assert patches.reads == patches.writes == []
    assert deletion.writes == []


async def test_empty_query_results_do_not_write_or_delete_implicitly() -> None:
    full = ProductBatchProjection({}, [])
    patches = ProductBatchPatchProjection({}, [])
    fanout = ProductFanoutProjection([], [])

    async def no_models(ids: Sequence[int]) -> Sequence[Product]:
        return []

    full._db_query = no_models
    assert await full.batch_project([7]) == []
    assert await patches.batch_project([7]) == []
    assert await fanout.project(7) == []
    assert full.writes == patches.writes == fanout.writes == []


@pytest.mark.parametrize("fanout", [False, True])
async def test_all_documents_convert_before_any_bulk_write(
    fanout: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = [Product(id=id, title=str(id)) for id in (7, 3)]
    failure = ValueError("invalid conversion")

    def fail_on_second(model: Product) -> ProductDocument:
        if model.id == 3:
            raise failure
        return product_document(model)

    if fanout:
        projection = ProductFanoutProjection(models, [])
        run = projection.project(7)
    else:
        projection = ProductBatchProjection({m.id: m for m in models}, [])
        run = projection.batch_project([7, 3])
    monkeypatch.setattr(projection, "_convert", fail_on_second)
    with pytest.raises(ValueError) as caught:
        await run
    assert caught.value is failure
    assert projection.writes == []


async def test_bulk_transport_error_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = ProductBatchUnProjection([])
    failure = ConnectionError("ES unavailable")
    calls = 0

    async def fail(ids: Sequence[int]) -> list[BulkItemResult]:
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(projection, "_es_query", fail)
    with pytest.raises(ConnectionError) as caught:
        await projection.batch_unproject([7, 3])
    assert caught.value is failure
    assert calls == 1


async def test_missing_source_can_abort_the_batch_before_writing() -> None:
    projection = ProductBatchProjection({7: Product(id=7, title="exists")}, [])
    with pytest.raises(KeyError) as caught:
        await projection.batch_project([7, 3])
    assert caught.value.args == (3,)
    assert projection.writes == []


async def test_batch_patch_conversion_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = ProductBatchPatchProjection(
        {7: ProductPatch(title="valid"), 3: ProductPatch(title=None)}, []
    )

    def convert(model: ProductPatch) -> ProductPatch:
        if model.title is None:
            raise ValueError("title is required by this projection")
        return model

    monkeypatch.setattr(projection, "_convert", convert)
    with pytest.raises(ValueError, match="title is required"):
        await projection.batch_project([7, 3])
    assert projection.writes == []


def test_projection_imports_do_not_load_runtimes_or_settings(
    tmp_path: Path,
) -> None:
    script = """
import sys
from fastamu.messaging.projections.contracts import convertor, delete, patch
assert 'elasticsearch' not in sys.modules
from fastamu.messaging.projections.contracts import base, policies, results
from fastamu.messaging.projections.repair import (
    orchestration, records, settlement,
)
assert 'redis' not in sys.modules
assert not any(
    name.startswith(('fastamu.core', 'fastamu.infra', 'fastamu.tasks',
                     'taskiq', 'faststream'))
    for name in sys.modules
)
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path, check=True)


async def test_batch_rebuilds_supplied_ids_from_current_source(
    bulk_results: list[BulkItemResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {id: Product(id=id, title=str(id)) for id in (7, 3)}
    projection = ProductBatchProjection(source, bulk_results)
    monkeypatch.setattr(projection, "_convert", ProductConvertor().convert)

    assert await projection.batch_project([7, 3]) is bulk_results
    assert projection.reads == [(7, 3)]
    assert [doc.meta.id for doc in projection.writes[0]] == ["7", "3"]
    assert not bulk_results[1].succeeded

    source[3] = Product(id=3, title="updated")
    assert await projection.batch_project([3]) is bulk_results
    assert projection.reads == [(7, 3), (3,)]
    assert projection.writes[1][0].to_dict() == {"title": "updated"}


async def test_batch_converter_failure_prevents_the_bulk_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConvertor(AbstractConvertor[Product, ProductDocument]):
        def convert(self, model: Product) -> ProductDocument:
            if model.id == 3:
                raise ValueError("invalid source")
            return product_document(model)

    source = {id: Product(id=id, title=str(id)) for id in (7, 3)}
    projection = ProductBatchProjection(source, [])
    monkeypatch.setattr(projection, "_convert", FailingConvertor().convert)

    with pytest.raises(ValueError, match="invalid source"):
        await projection.batch_project([7, 3])
    assert projection.writes == []
