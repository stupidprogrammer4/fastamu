"""What counts as done, and which inputs still need another attempt."""

import pytest

from fastamu.messaging.projections.contracts.results import (
    BulkItemResult,
    ProjectionBatchError,
)
from fastamu.messaging.projections.repair.records import FailureRecord
from fastamu.messaging.projections.repair.settlement import (
    settled_ids,
    unresolved_ids,
    unsettled,
)


def record(input_id: int, attempts: int = 0) -> FailureRecord:
    return FailureRecord(
        input_id=input_id,
        error="failed",
        failed_at=1.0,
        attempts=attempts,
    )


@pytest.mark.parametrize(
    "status,succeeded",
    [(200, True), (201, True), (404, False), (409, False), (500, False)],
)
def test_only_a_2xx_write_succeeded(status: int, succeeded: bool) -> None:
    item = BulkItemResult(id="7", status=status)
    assert item.succeeded is succeeded
    assert item.settled is succeeded


def test_the_writer_decides_a_failed_status_is_final() -> None:
    conflict = BulkItemResult(
        id="7",
        status=409,
        error={"type": "version_conflict_engine_exception"},
        final=True,
    )

    assert not conflict.succeeded
    assert conflict.settled


def test_batch_error_counts_only_unsettled_items() -> None:
    error = ProjectionBatchError(
        [
            BulkItemResult(id="7", status=409, final=True),
            BulkItemResult(id="8", status=404),
            BulkItemResult(id="9", status=500),
        ]
    )
    assert str(error) == "2 projection operations failed"


def test_an_id_reported_both_ways_is_not_settled() -> None:
    results = [
        BulkItemResult(id="7", status=200),
        BulkItemResult(id="7", status=500),
    ]
    assert settled_ids(results) == set()


def test_unsettled_records_keep_their_place_in_the_queue() -> None:
    records = [record(7), record(8, attempts=2), record(9)]
    results = [
        BulkItemResult(id="7", status=200),
        BulkItemResult(id="8", status=409, final=True),
        BulkItemResult(id="9", status=500),
    ]

    pending = unsettled(records, results)

    assert [row.input_id for row in pending] == [9]
    assert pending[0].attempts == 0


def test_a_result_that_does_not_describe_every_id_explains_none() -> None:
    records = [record(7), record(8)]
    partial = [BulkItemResult(id="7", status=200)]

    assert unsettled(records, partial) == records
    assert unsettled(records, []) == records
    assert unresolved_ids([7, 8], partial) == [7, 8]


def test_a_complete_result_drops_what_it_settled() -> None:
    complete = [
        BulkItemResult(id="7", status=409, final=True),
        BulkItemResult(id="8", status=500),
    ]
    assert unresolved_ids([7, 8], complete) == [8]
    assert unsettled([record(7), record(8)], complete)[0].input_id == 8
