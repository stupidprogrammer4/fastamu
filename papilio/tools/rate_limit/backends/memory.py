from collections.abc import Sequence

from throttled import types
from throttled.asyncio.rate_limiter.sliding_window import (
    MemoryLimitAtomicAction,
)
from throttled.asyncio.store import MemoryStore
from throttled.store import BaseMemoryStoreBackend

from .base import ThrottledBackend


class _MemoryAction(MemoryLimitAtomicAction):
    @classmethod
    def _do(
        cls,
        backend: BaseMemoryStoreBackend,
        keys: Sequence[str],
        args: Sequence[types.StoreValueT] | None,
    ) -> tuple[int, int, float]:
        # 3.4.1 inserts a new bucket before checking its weighted budget.
        # Undo that insertion on rejection, inside the native atomic lock.
        absent = backend.get(keys[0]) is None
        result = super()._do(backend, keys, args)
        if absent and result[0]:
            backend.delete(keys[0])
        return result


class MemoryBackend(ThrottledBackend):
    """Counters local to this instance/process, with bounded memory."""

    def __init__(self, *, max_size: int = 10000) -> None:
        super().__init__(
            MemoryStore(options={"MAX_SIZE": max_size}),
            actions=(_MemoryAction,),
        )
