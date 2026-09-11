"""Durable publication intent; the UUID identifies every delivery attempt."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    kind: Literal["event", "projection"]
    target: str
    payload: bytes
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        if self.kind not in ("event", "projection"):
            raise ValueError("Unsupported outbox message kind")
        if not self.target.strip() or len(self.target) > 255:
            raise ValueError("Outbox target must contain 1 to 255 characters")
