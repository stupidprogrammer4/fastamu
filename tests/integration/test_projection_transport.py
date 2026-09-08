"""Run with FASTAMU_RABBIT_TEST_URL against a disposable RabbitMQ instance."""

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dishka import Provider, Scope, provide

from fastamu.common.projections.base import AbstractProjection
from fastamu.common.projections.queue import ProjectionQueue
from fastamu.core.config import ProjectionConfig


async def test_shared_broker_serializes_each_queue_but_not_other_queues(
    monkeypatch,
):
    url = os.environ.get("FASTAMU_RABBIT_TEST_URL")
    if not url:
        pytest.skip("Set FASTAMU_RABBIT_TEST_URL for RabbitMQ transport tests")

    from fastamu.common.projections import queue as queue_module
    from fastamu.tasks.projection import broker as broker_module
    from fastamu.tasks.projection import receiver as receiver_module
    from fastamu.tasks.projection import registry as registry_module

    config = ProjectionConfig(url=url, retry_delay=0.03)
    registry = registry_module.ProjectionRegistry()
    broker = broker_module.create_broker(config)
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    monkeypatch.setattr(receiver_module, "get_settings", lambda: settings)
    monkeypatch.setattr(broker_module, "broker", broker)
    prefix = uuid4().hex
    seen = []
    order_finished = asyncio.Event()
    product_finished = asyncio.Event()
    attempts = []

    class Product(AbstractProjection):
        queue_name = prefix + ".products"

        async def _db_query(self, id):
            return None

        async def _es_query(self, document):
            pass

        async def project(self, id):
            seen.append(("product", id))
            if id == 1:
                attempts.append(self)
                if len(attempts) == 1:
                    await asyncio.wait_for(order_finished.wait(), 5)
                    raise RuntimeError("retry A before B")
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
    receiver = receiver_module.ProjectionReceiver(broker)
    deliveries = []

    async def consume():
        async for message in broker.listen():
            deliveries.append(asyncio.create_task(receiver.callback(message)))

    listener = asyncio.create_task(consume())
    try:
        await ProjectionQueue().queue(Product, 1)
        await ProjectionQueue().queue(Update, 2)
        await ProjectionQueue().queue(Order, 3)
        await asyncio.wait_for(product_finished.wait(), 10)
        await asyncio.gather(*deliveries)
        products = [
            x for x in seen if isinstance(x, tuple) and x[0] == "product"
        ]
        assert products == [("product", 1), ("product", 1), ("product", 2)]
        assert seen.index(("order", 3)) < seen.index(("product", 2))
        assert attempts[0] is not attempts[1]
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
