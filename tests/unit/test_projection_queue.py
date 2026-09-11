from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import AckableMessage
from taskiq.receiver import Receiver

from fastamu.core.config import ProjectionConfig
from fastamu.messaging.retry import RetryPolicy
from fastamu.projections import definition
from fastamu.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.tasks.projection import broker as broker_module
from fastamu.tasks.projection import publisher as queue_module
from fastamu.tasks.projection import registry as registry_module
from fastamu.tasks.projection.publisher import publish
from fastamu.tasks.projection.registry import ProjectionRegistry


@pytest.fixture
def runtime(monkeypatch):
    config = ProjectionConfig(url="amqp://localhost")
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    monkeypatch.setattr(definition, "definitions", {})
    registry = ProjectionRegistry()
    broker = broker_module.create_broker(config)
    monkeypatch.setattr(broker_module, "broker", broker)
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    broker.kick = AsyncMock()
    return registry, broker, config


def define_projections():
    class CreateProduct(AbstractProjection):
        queue_name = "products"

        async def _db_query(self, id):
            return None

        async def _es_query(self, document):
            pass

    class UpdateProduct(CreateProduct):
        pass

    class Order(CreateProduct):
        queue_name = "orders"

    class Batch(AbstractBatchProjection):
        queue_name = "products"

        async def _db_query(self, ids):
            return []

        async def _es_query(self, documents):
            pass

    class Fanout(AbstractFanoutProjection):
        queue_name = "products"

        async def _db_query(self, id):
            return []

        async def _es_query(self, documents):
            pass

    class Remove(AbstractUnProjection):
        queue_name = "products"

        async def _es_query(self, id):
            pass

    return CreateProduct, UpdateProduct, Order, Batch, Fanout, Remove


def test_one_broker_multiple_queues_multiple_tasks_and_idempotent_build(
    runtime,
):
    registry, broker, _ = runtime
    classes = define_projections()
    registry.build(broker)
    registry.build(broker)
    assert set(registry.queues) == {"products", "orders"}
    assert len(broker._task_queues) == 2
    assert len(broker.get_all_tasks()) == len(classes)
    assert all(task.broker is broker for task in registry.tasks.values())
    assert broker._qos == 1
    assert all(
        q.arguments["x-single-active-consumer"] for q in broker._task_queues
    )


async def test_publish_only_and_batch_is_one_message(runtime):
    registry, broker, _ = runtime
    single, _, _, batch, fanout, _ = define_projections()
    registry.build(broker)
    await publish(single, 7)
    await publish(batch, [1, 2, 1])
    await publish(batch, [])
    await publish(fanout, 3)
    messages = [
        broker.formatter.loads(message=c.args[0].message)
        for c in broker.kick.call_args_list
    ]
    assert [m.args for m in messages] == [[7], [[1, 2]], [3]]
    assert all(m.labels["queue_name"] == "products" for m in messages)
    assert all("projection_expires_at" not in m.labels for m in messages)


async def test_registry_dispatches_fanout_with_one_id():
    *_, fanout, _ = define_projections()
    instance = SimpleNamespace(project=AsyncMock())

    await ProjectionRegistry._handler(fanout)(7, instance)

    instance.project.assert_awaited_once_with(7)


@pytest.mark.parametrize("fails", [False, True])
async def test_executes_once_and_closes_scope_before_ack(runtime, fails):
    registry, broker, _ = runtime
    single, *_ = define_projections()
    seen = []
    instances = []

    class Dependencies(Provider):
        @provide(scope=Scope.REQUEST, provides=single)
        async def projection(self) -> AsyncIterator[object]:
            instance = single(None)
            instances.append(instance)

            async def project(id):
                seen.append(id)
                if fails:
                    raise RuntimeError("temporary failure")

            instance.project = project
            try:
                yield instance
            finally:
                seen.append("closed")

    registry.build(broker)
    container = make_async_container(TaskiqProvider(), Dependencies())
    setup_dishka(container, broker)
    # Only the tested task has a provider; dependency resolution is lazy.
    receiver = Receiver(broker)
    await publish(single, 9)
    ack = AsyncMock(side_effect=lambda: seen.append("ack"))
    delivery = AckableMessage(
        data=broker.kick.call_args.args[0].message, ack=ack
    )
    try:
        await receiver.callback(delivery)
        assert seen == [9, "closed", "ack"]
        assert len(instances) == 1
        broker.kick.assert_awaited_once()
    finally:
        await container.close()


@pytest.mark.parametrize("shape", ["single", "batch", "fanout", "remove"])
async def test_projection_handlers_execute_without_sql_tickets(runtime, shape):
    single, _, _, batch, fanout, remove = define_projections()
    classes = dict(single=single, batch=batch, fanout=fanout, remove=remove)
    instance = SimpleNamespace(
        project=AsyncMock(), batch_project=AsyncMock(), unproject=AsyncMock()
    )
    argument = [7] if shape == "batch" else 7
    await ProjectionRegistry._handler(classes[shape])(argument, instance)
    method = {"batch": "batch_project", "remove": "unproject"}.get(
        shape, "project"
    )
    getattr(instance, method).assert_awaited_once_with(argument)


async def test_retry_resolves_fresh_projection_scope_per_attempt(runtime):
    registry, broker, _ = runtime
    single, *_ = define_projections()
    single.retry_policy = RetryPolicy(max_attempts=3, delays=(1,), jitter=0)
    seen = []
    instances = []

    class Dependencies(Provider):
        @provide(scope=Scope.REQUEST, provides=single)
        async def projection(self) -> AsyncIterator[object]:
            instance = single(None)
            instances.append(instance)

            async def project(id):
                seen.append(id)
                if len(instances) < 3:
                    raise RuntimeError("transient")

            instance.project = project
            try:
                yield instance
            finally:
                seen.append("closed")

    registry.build(broker)
    container = make_async_container(TaskiqProvider(), Dependencies())
    setup_dishka(container, broker)
    receiver = Receiver(broker)
    await publish(single, 9)
    try:
        for _ in range(3):
            delivery = AckableMessage(
                data=broker.kick.call_args.args[0].message,
                ack=AsyncMock(side_effect=lambda: seen.append("ack")),
            )
            await receiver.callback(delivery)
        assert seen == [9, "closed", "ack"] * 3
        assert len({id(instance) for instance in instances}) == 3
        assert broker.kick.await_count == 3
    finally:
        await container.close()
