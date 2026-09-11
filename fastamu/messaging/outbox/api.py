"""Explicit application API for atomic recording and immediate delivery."""

from fastamu.messaging.outbox.events import event, record_event
from fastamu.messaging.outbox.projections import (
    batch_projection,
    fanout_projection,
    projection,
    record_batch_projection,
    record_projection,
    unprojection,
)
from fastamu.messaging.outbox.scope import deliver, delivery

__all__ = [
    "deliver",
    "delivery",
    "event",
    "record_event",
    "projection",
    "batch_projection",
    "fanout_projection",
    "unprojection",
    "record_projection",
    "record_batch_projection",
]
