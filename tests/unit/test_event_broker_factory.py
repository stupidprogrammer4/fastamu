from unittest.mock import AsyncMock, patch

import pytest
from faststream.rabbit import Channel
from pydantic import ValidationError

from fastamu.core.config import EventsConfig
from fastamu.tasks.events.factory import BrokerFactory


@pytest.mark.parametrize(
    ("name", "url", "target"),
    [
        (
            "rabbitmq",
            "amqp://localhost/test",
            "fastamu.tasks.events.factory.RabbitBroker",
        ),
        (
            "redis",
            "redis://localhost:6379/3",
            "fastamu.tasks.events.factory.RedisBroker",
        ),
    ],
)
def test_selects_transport_and_passes_url_without_starting(name, url, target):
    config = EventsConfig(broker=name, url=url)
    with patch(target) as constructor:
        broker = BrokerFactory.create(config)
        if name == "rabbitmq":
            constructor.assert_called_once_with(
                url, default_channel=Channel(on_return_raises=True)
            )
        else:
            constructor.assert_called_once_with(url)
        assert broker is constructor.return_value
        broker.connect.assert_not_called()
        broker.start.assert_not_called()


def test_memory_is_not_a_supported_configuration():
    with pytest.raises(ValidationError):
        EventsConfig(broker="memory", url="unused")


def test_generated_config_builds_real_brokers_without_network():
    import yaml
    from faststream.rabbit import RabbitBroker
    from faststream.redis import RedisBroker

    from fastamu.scaffold import CONFIG_YML

    config = EventsConfig.model_validate(
        yaml.safe_load(CONFIG_YML)["tasks"]["events"]
    )
    assert isinstance(BrokerFactory.create(config), RabbitBroker)
    redis_config = EventsConfig(broker="redis", url="redis://localhost:6379/3")
    assert isinstance(BrokerFactory.create(redis_config), RedisBroker)


async def test_rabbit_event_publish_uses_configured_topic_exchange(
    monkeypatch,
):
    from fastamu.tasks.events import broker as event_module
    from fastamu.tasks.events.publisher import publish

    sent = AsyncMock()
    monkeypatch.setattr(event_module.broker, "publish", sent)

    await publish("catalog.changed", {"value": 7})

    sent.assert_awaited_once_with(
        {"value": 7},
        exchange=event_module.rabbit_exchange(),
        routing_key="catalog.changed",
        persist=True,
    )
