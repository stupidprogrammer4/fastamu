import logging
from collections.abc import Iterable, Sequence

from fastamu.messaging.projections.repair.records import FailureStore

logger = logging.getLogger(__name__)


def reason(error: BaseException) -> str:
    """Keep the cause, because a transport error's own message is generic."""
    cause = error.__cause__
    return f"{error}" if cause is None else f"{error}: {cause}"


class PublicationFallback:
    """Queue what could not be published, when repair can pick it up.

    A publication failure lands after the commit, so raising it would report
    a write that succeeded as failed.
    """

    def __init__(self) -> None:
        self.store: FailureStore | None = None
        self.repaired: frozenset[str] = frozenset()

    def use(self, store: FailureStore, repaired: Iterable[str]) -> None:
        self.store = store
        self.repaired = frozenset(repaired)

    def clear(self) -> None:
        self.store = None
        self.repaired = frozenset()

    async def queued(
        self,
        task_name: str,
        ids: Sequence[int],
        error: BaseException,
    ) -> bool:
        """Take responsibility for these IDs, or report that nothing did.

        Only a projection with a repair target is queued — any other list
        would grow with nothing to drain it. Without repair configured
        there is no backstop, so the caller sees the failure.
        """
        store = self.store if task_name in self.repaired else None
        if store is not None:
            try:
                await store.record(task_name, ids, reason(error))
            except Exception:
                logger.exception(
                    "Could not queue %d %s inputs after a publication"
                    " failure: %s. They stay unreflected until"
                    " reconciliation finds them",
                    len(ids),
                    task_name,
                    reason(error),
                )
            else:
                logger.warning(
                    "Queued %d %s inputs for repair after a publication"
                    " failure: %s",
                    len(ids),
                    task_name,
                    reason(error),
                )
        return store is not None


fallback = PublicationFallback()
