import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

from fastamu.messaging.projections.contracts.results import BulkItemResult
from fastamu.messaging.projections.repair.records import FailureStore
from fastamu.messaging.projections.repair.settlement import unsettled

logger = logging.getLogger(__name__)

type RepairTarget = Callable[[Sequence[int]], Awaitable[list[BulkItemResult]]]


class Repair:
    """Take a bounded batch of unreflected inputs and run them.

    Repair executes rather than publishes, so nothing is settled on a
    promise. Projections share nothing, so they run up to `concurrency`
    at a time.
    """

    def __init__(
        self,
        store: FailureStore,
        targets: Mapping[str, RepairTarget],
        batch_size: int,
        concurrency: int = 4,
    ) -> None:
        self.store = store
        self.targets = targets
        self.batch_size = batch_size
        self.concurrency = concurrency

    async def run(self) -> int:
        limit = asyncio.Semaphore(self.concurrency)

        async def guarded(name: str, target: RepairTarget) -> int:
            async with limit:
                return await self._repair(name, target)

        outcomes = await asyncio.gather(
            *(guarded(name, target) for name, target in self.targets.items()),
            return_exceptions=True,
        )
        repaired = 0
        for name, outcome in zip(self.targets, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                # one unreachable queue must not abandon the rest
                logger.error(
                    "Could not repair projection: %s",
                    name,
                    exc_info=outcome,
                )
            else:
                repaired += outcome
        return repaired

    async def _repair(self, name: str, target: RepairTarget) -> int:
        repaired = 0
        records = await self.store.take(name, self.batch_size)
        if records:
            ids = list(dict.fromkeys(record.input_id for record in records))
            try:
                results = await target(ids)
            except Exception:
                logger.exception("Projection repair failed to run: %s", name)
                await self.store.requeue(name, records)
            else:
                pending = unsettled(records, results)
                await self.store.requeue(name, pending)
                repaired = len(records) - len(pending)
        return repaired
