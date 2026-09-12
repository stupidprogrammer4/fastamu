from collections.abc import Sequence

from fastamu.messaging.projections.contracts.results import BulkItemResult
from fastamu.messaging.projections.repair.records import FailureRecord


def settled_ids(results: Sequence[BulkItemResult]) -> set[str]:
    """Return destination IDs that need no repeat and never failed."""
    settled: set[str] = set()
    failed: set[str] = set()
    for item in results:
        (settled if item.settled else failed).add(item.id)
    return settled - failed


def _trusted(ids: Sequence[int], results: Sequence[BulkItemResult]) -> bool:
    """A result that omits an ID says nothing about it."""
    return {item.id for item in results} == {str(id) for id in ids}


def unresolved_ids(
    ids: Sequence[int],
    results: Sequence[BulkItemResult],
) -> list[int]:
    unresolved = list(ids)
    if _trusted(ids, results):
        settled = settled_ids(results)
        unresolved = [id for id in ids if str(id) not in settled]
    return unresolved


def unsettled(
    records: Sequence[FailureRecord],
    results: Sequence[BulkItemResult],
) -> list[FailureRecord]:
    ids = [record.input_id for record in records]
    pending = list(records)
    if _trusted(ids, results):
        settled = settled_ids(results)
        pending = [
            record for record in records if str(record.input_id) not in settled
        ]
    return pending
