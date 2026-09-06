from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class BatchResultType[T, E]:
    """A clean, named return value for batch lookups — a typed stand-in for a
    bare tuple, no validation. Carries the resolved ``items``, the per-item
    ``errors`` for the ones that failed, and the set of ids that resolved."""

    items: Sequence[T]
    errors: Sequence[E]
    item_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class PagedType[T]:
    items: Sequence[T]
    total_items: int
