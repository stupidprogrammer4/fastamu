import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import ClassVar

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from pydantic import ValidationError
from taskiq import InMemoryBroker

from fastamu.messaging.projections.contracts.delete import AbstractUnProjection
from fastamu.messaging.projections.contracts.results import (
    BulkItemResult,
    ProjectionBatchError,
)
from fastamu.tasks.projection.delivery.register import Register
from tests.unit.test_projection import (
    Product,
    ProductBatchPatchProjection,
    ProductBatchProjection,
    ProductBatchUnProjection,
    ProductDocument,
    ProductFanoutProjection,
    ProductPatch,
    ProductPatchProjection,
    ProductProjection,
    ProductUnProjection,
    product_document,
)


@dataclass
class Trace:
    opened: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)
    writes: list[tuple[str, int, int]] = field(default_factory=list)


@dataclass
class Resource:
    number: int
    trace: Trace


class DeleteProduct(AbstractUnProjection):
    queue_name: ClassVar[str] = "products"

    def __init__(self, resource: Resource) -> None:
        self.resource = resource

    async def _es_query(self, id: int) -> None:
        await asyncio.sleep(0)
        self.resource.trace.writes.append(
            (type(self).__name__, self.resource.number, id)
        )
        if id < 0:
            raise LookupError("invalid product")


class DeleteProductPrice(DeleteProduct):
    pass


class DeleteVariant(DeleteProduct):
    queue_name: ClassVar[str] = "variants"


class Resources(Provider):
    @provide(scope=Scope.REQUEST)
    async def resource(self, trace: Trace) -> AsyncIterator[Resource]:
        number = len(trace.opened)
        trace.opened.append(number)
        try:
            yield Resource(number, trace)
        finally:
            trace.closed.append(number)


async def test_native_tasks_dispatch_with_fresh_scopes_and_cleanup() -> None:
    registry = Register()
    broker = InMemoryBroker(await_inplace=True)
    trace = Trace()
    provider = Resources()
    provider.provide(lambda: trace, provides=Trace, scope=Scope.APP)
    provider.provide_all(
        DeleteProduct, DeleteProductPrice, DeleteVariant, scope=Scope.REQUEST
    )
    container = make_async_container(TaskiqProvider(), provider)
    setup_dishka(container, broker)
    classes = (DeleteProduct, DeleteProductPrice, DeleteVariant)
    for projection in classes:
        registry.register(projection, broker)

    assert trace.opened == []
    assert len(registry.tasks) == 3
    assert len({task.task_name for task in registry.tasks.values()}) == 3
    assert [registry.get(cls).labels["queue_name"] for cls in classes] == [
        "products",
        "products",
        "variants",
    ]

    await broker.startup()
    try:
        sent = await asyncio.gather(
            registry.get(DeleteProduct).kiq(id=7),
            registry.get(DeleteProductPrice).kiq(id=3),
            registry.get(DeleteVariant).kiq(id=9),
            registry.get(DeleteProduct).kiq(id=-1),
        )
        results = await asyncio.gather(*(task.wait_result() for task in sent))
        assert [result.is_err for result in results] == [
            False,
            False,
            False,
            True,
        ]
        assert isinstance(results[-1].error, LookupError)
        assert {(name, id) for name, _, id in trace.writes} == {
            ("DeleteProduct", 7),
            ("DeleteProductPrice", 3),
            ("DeleteVariant", 9),
            ("DeleteProduct", -1),
        }
        assert len({number for _, number, _ in trace.writes}) == 4
        assert sorted(trace.closed) == trace.opened == [0, 1, 2, 3]
    finally:
        await broker.shutdown()
        await container.close()


async def test_all_projection_shapes_use_their_own_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {7: Product(id=7, title="product")}
    documents: list[ProductDocument] = []

    async def read(id: int) -> Product:
        return source[id]

    async def write(document: ProductDocument) -> None:
        documents.append(document)

    full = ProductProjection(read, product_document, write)
    patch = ProductPatchProjection(ProductPatch(title="new"))
    delete = ProductUnProjection()
    batch = ProductBatchProjection(source, [])
    batch_patch = ProductBatchPatchProjection(
        {7: ProductPatch(title=None)}, []
    )
    batch_delete = ProductBatchUnProjection([])
    fanout = ProductFanoutProjection(list(source.values()), [])
    projections = (
        full,
        patch,
        delete,
        batch,
        batch_patch,
        batch_delete,
        fanout,
    )
    registry = Register()
    broker = InMemoryBroker(await_inplace=True)
    provider = Provider()

    for instance in projections:
        cls = type(instance)
        monkeypatch.setattr(cls, "queue_name", "products", raising=False)

        provider.from_context(cls, scope=Scope.APP)
        registry.register(cls, broker)

    container = make_async_container(
        TaskiqProvider(),
        provider,
        context={type(instance): instance for instance in projections},
    )
    setup_dishka(container, broker)
    await broker.startup()
    try:
        for instance in (full, patch, delete, fanout):
            sent = await registry.get(type(instance)).kiq(id=7)
            assert not (await sent.wait_result()).is_err
        for instance in (batch, batch_patch, batch_delete):
            sent = await registry.get(type(instance)).kiq(ids=[7])
            assert not (await sent.wait_result()).is_err

        assert len(documents) == 1
        assert len(patch.writes) == 1
        assert delete.deleted == [7]
        assert batch.reads == [(7,)]
        assert len(batch.writes) == 1
        assert len(batch_patch.writes) == 1
        assert batch_delete.writes == [(7,)]
        assert fanout.reads == [7]
        assert len(fanout.writes) == 1

        batch.results = [BulkItemResult(id="7", status=500)]
        sent = await registry.get(ProductBatchProjection).kiq(ids=[7])
        result = await sent.wait_result()
        assert isinstance(result.error, ProjectionBatchError)
        assert result.error.results == batch.results
    finally:
        await broker.shutdown()
        await container.close()


def test_register_is_idempotent_and_rejects_another_broker() -> None:
    registry = Register()
    broker = InMemoryBroker()
    task = registry.register(DeleteProduct, broker)
    assert registry.register(DeleteProduct, broker) is task
    assert registry.get(DeleteProduct) is broker.find_task(task.task_name)
    assert len(registry.tasks) == 1
    with pytest.raises(ValueError, match="another broker"):
        registry.register(DeleteProduct, InMemoryBroker())
    assert registry.get(DeleteProduct) is task


def test_register_rejects_name_collision_without_overwriting() -> None:
    registry = Register()
    broker = InMemoryBroker()

    async def existing(id: int) -> None:
        pass

    name = f"{DeleteProduct.__module__}:{DeleteProduct.__qualname__}"
    task = broker.task(task_name=name)(existing)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(DeleteProduct, broker)
    assert registry.tasks == {}
    assert broker.find_task(name) is task


def test_register_rejects_abstract_projection() -> None:
    with pytest.raises(TypeError, match="abstract projection"):
        Register().register(AbstractUnProjection, InMemoryBroker())


@pytest.mark.parametrize("queue_name", [None, "", 123])
def test_register_validates_queue_before_registering(
    queue_name: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DeleteProduct, "queue_name", queue_name)
    registry = Register()
    broker = InMemoryBroker()
    with pytest.raises(ValidationError):
        registry.register(DeleteProduct, broker)
    assert registry.tasks == {}
    assert broker.get_all_tasks() == {}


def test_get_unregistered_projection_raises_key_error() -> None:
    with pytest.raises(KeyError):
        Register().get(DeleteProduct)
