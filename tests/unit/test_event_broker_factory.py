from unittest.mock import patch

import pytest
from pydantic import ValidationError

from fastamu.core.config import EventsConfig
from fastamu.tasks.events.factory import BrokerFactory


@pytest.mark.parametrize(
    ("name", "url", "target"),
    [
        (
            "rabbitmq",
            "amqp://localhost/test",
            "faststream.rabbit.RabbitBroker",
        ),
        ("redis", "redis://localhost:6379/3", "faststream.redis.RedisBroker"),
    ],
)
def test_selects_transport_and_passes_url_without_starting(name, url, target):
    config = EventsConfig(broker=name, url=url)
    with patch(target) as constructor:
        broker = BrokerFactory.create(config)
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
