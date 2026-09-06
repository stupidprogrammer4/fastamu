"""The configured event broker. Importing does not open a connection."""

from fastamu.core.config import get_settings
from fastamu.tasks.events.factory import BrokerFactory

event_cfg = get_settings().tasks.events
if event_cfg is None:
    raise RuntimeError("Events are disabled; configure tasks.events")
broker = BrokerFactory.create(event_cfg)
