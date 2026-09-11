"""Run with FASTAMU_RABBIT_TEST_URL against a disposable RabbitMQ instance."""

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dishka import Provider, Scope, provide
from taskiq.receiver import Receiver

from fastamu.core.config import ProjectionConfig
from fastamu.projections import definition
from fastamu.projections.base import AbstractProjection
from fastamu.tasks.projection.publisher import publish


@pytest.mark.parametrize("fails", [False, True])
async def test_shared_broker_serializes_each_queue_without_retry(
    monkeypatch,
    fails,
):
    url = os.environ.get("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL for RabbitMQ transport tests")

    from fastamu.tasks.projection import broker as broker_module
    from fastamu.tasks.projection import publisher as queue_module
    from fastamu.tasks.projection import registry as registry_module

    config = ProjectionConfig(url=url)
    monkeypatch.setattr(definition, "definitions", {})
    registry = registry_module.ProjectionRegistry()
    broker = broker_module.create_broker(config)
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    monkeypatch.setattr(broker_module, "broker", broker)
    prefix = uuid4().hex
    seen = []
    order_finished = asyncio.Event()
    product_finished = asyncio.Event()

    class Product(AbstractProjection):
        queue_name = prefix + ".products"

        async def _db_query(self, id):
            return None

        async def _es_query(self, document):
            pass

        async def project(self, id):
            seen.append(("product", id))
            if id == 1:
                await asyncio.wait_for(order_finished.wait(), 5)
                if fails:
                    raise RuntimeError("failed projection is not retried")
            else:
                product_finished.set()

    class Update(Product):
        pass

    class Order(Product):
        queue_name = prefix + ".orders"

        async def project(self, id):
            seen.append(("order", id))
            order_finished.set()

    class Dependencies(Provider):
        @provide(scope=Scope.REQUEST)
        async def product(self) -> AsyncIterator[Product]:
            yield Product(None)
            seen.append("closed")

        @provide(scope=Scope.REQUEST)
        async def update(self) -> AsyncIterator[Update]:
            yield Update(None)
            seen.append("closed")

        @provide(scope=Scope.REQUEST)
        async def order(self) -> AsyncIterator[Order]:
            yield Order(None)
            seen.append("closed")

    monkeypatch.setattr(
        broker_module,
        "get_bootstrapper",
        lambda: SimpleNamespace(boot_providers=lambda: [Dependencies()]),
    )
    registry.build(broker)
    broker.is_worker_process = True
    await broker.startup()
    receiver = Receiver(broker)
    deliveries = []

    async def consume():
        async for message in broker.listen():
            deliveries.append(asyncio.create_task(receiver.callback(message)))

    listener = asyncio.create_task(consume())
    try:
        await publish(Product, 1)
        await publish(Update, 2)
        await publish(Order, 3)
        await asyncio.wait_for(product_finished.wait(), 10)
        await asyncio.gather(*deliveries)
        products = [
            x for x in seen if isinstance(x, tuple) and x[0] == "product"
        ]
        assert products == [("product", 1), ("product", 2)]
        assert seen.index(("order", 3)) < seen.index(("product", 2))
        assert len(broker._task_queues) == 2
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
        for task in deliveries:
            task.cancel()
        await asyncio.gather(*deliveries, return_exceptions=True)
        for name in registry.queues:
            queue = await broker.write_channel.get_queue(name)
            await queue.delete(if_unused=False, if_empty=False)
        await broker.shutdown()
