"""One projection broker consuming its registered domain queues."""

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.tasks.projection.broker import broker
from fastamu.tasks.projection.registry import registry


def get_broker():
    get_bootstrapper().boot_projections()
    registry.build()
    if not registry.queues:
        raise ValueError("No projection queues registered")
    return broker
