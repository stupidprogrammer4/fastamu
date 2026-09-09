from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import AckableMessage

from fastamu.common.projections import queue as queue_module
from fastamu.common.projections.base import (
    AbstractBatchProjection,
    AbstractFanoutProjection,
    AbstractProjection,
    AbstractUnProjection,
)
from fastamu.common.projections.queue import (
    BatchProjectionQueue,
    ProjectionQueue,
)
from fastamu.core.config import ProjectionConfig
from fastamu.tasks.projection import broker as broker_module
from fastamu.tasks.projection import receiver as receiver_module
from fastamu.tasks.projection import registry as registry_module
from fastamu.tasks.projection.registry import ProjectionRegistry


@pytest.fixture
def runtime(monkeypatch):
    config = ProjectionConfig(url="amqp://localhost", retry_delay=0.001)
    settings = SimpleNamespace(tasks=SimpleNamespace(projection=config))
    registry = ProjectionRegistry()
    broker = broker_module.create_broker(config)
    monkeypatch.setattr(broker_module, "broker", broker)
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(queue_module, "registry", registry)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    monkeypatch.setattr(receiver_module, "get_settings", lambda: settings)
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
    await ProjectionQueue().queue(single, 7)
    await BatchProjectionQueue().queue(batch, [1, 2, 1])
    await BatchProjectionQueue().queue(batch, [])
    await ProjectionQueue().queue(fanout, 3)
    messages = [
        broker.formatter.loads(message=c.args[0].message)
        for c in broker.kick.call_args_list
    ]
    assert [m.args for m in messages] == [[7], [[1, 2]], [3]]
    assert all(m.labels["queue_name"] == "products" for m in messages)


async def test_registry_dispatches_fanout_with_one_id():
    *_, fanout, _ = define_projections()
    instance = SimpleNamespace(project=AsyncMock())

    await ProjectionRegistry._handler(fanout)(
        7, instance, SimpleNamespace(labels={}), None
    )

    instance.project.assert_awaited_once_with(7)


async def test_retry_uses_fresh_dishka_scope_and_acks_after_cleanup(runtime):
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
                if len(instances) == 1:
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
    receiver = receiver_module.ProjectionReceiver(broker)
    await ProjectionQueue().queue(single, 9)
    ack = AsyncMock(side_effect=lambda: seen.append("ack"))
    delivery = AckableMessage(
        data=broker.kick.call_args.args[0].message, ack=ack
    )
    try:
        await receiver.callback(delivery)
        assert seen == [9, "closed", 9, "closed", "ack"]
        assert instances[0] is not instances[1]
    finally:
        await container.close()


async def test_exhaustion_lets_the_queue_move_on(runtime):
    registry, broker, config = runtime
    config.max_retries = 0
    single, *_ = define_projections()
    registry.build(broker)
    receiver = receiver_module.ProjectionReceiver(broker)
    seen = []
    receiver.recovery.store = AsyncMock(
        side_effect=lambda failure: seen.append("stored")
    )
    await ProjectionQueue().queue(single, 1)
    ack = AsyncMock(side_effect=lambda: seen.append("ack"))
    delivery = AckableMessage(
        data=broker.kick.call_args.args[0].message, ack=ack
    )
    await receiver.callback(delivery)

    ack.assert_awaited_once()
    assert seen == ["stored", "ack"]
    failure = receiver.recovery.store.call_args.args[0]
    assert failure.message.args == [1]
    assert failure.queue == "products"
    assert failure.attempts == 1


async def test_failure_storage_error_never_acks_original(runtime):
    import asyncio

    registry, broker, config = runtime
    config.max_retries = 0
    single, *_ = define_projections()
    registry.build(broker)
    receiver = receiver_module.ProjectionReceiver(broker)
    stored = asyncio.Event()

    async def unavailable(failure):
        stored.set()
        raise ConnectionError("RabbitMQ unavailable")

    receiver.recovery.store = unavailable
    await ProjectionQueue().queue(single, 1)
    ack = AsyncMock()
    task = asyncio.create_task(
        receiver.callback(
            AckableMessage(data=broker.kick.call_args.args[0].message, ack=ack)
        )
    )
    await asyncio.wait_for(stored.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ack.assert_not_awaited()


@pytest.mark.parametrize("shape", ["single", "batch", "fanout", "remove"])
async def test_every_projection_shape_checks_its_producer_before_execution(
    runtime, monkeypatch, shape
):
    from fastamu.infra.db.versions import ProjectionPending

    single, _, _, batch, fanout, remove = define_projections()
    classes = dict(single=single, batch=batch, fanout=fanout, remove=remove)
    check = AsyncMock(side_effect=ProjectionPending)
    monkeypatch.setattr(registry_module, "_prepare_execution", check)
    instance = SimpleNamespace(
        project=AsyncMock(), batch_project=AsyncMock(), unproject=AsyncMock()
    )
    message = SimpleNamespace(labels={})
    handler = ProjectionRegistry._handler(classes[shape])
    with pytest.raises(ProjectionPending):
        await handler([7] if shape == "batch" else 7, instance, message, None)
    check.assert_awaited_once_with(message, None, classes[shape], [7])
    instance.project.assert_not_awaited()
    instance.batch_project.assert_not_awaited()
    instance.unproject.assert_not_awaited()
