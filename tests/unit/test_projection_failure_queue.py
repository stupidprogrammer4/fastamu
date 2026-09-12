"""The queue of unreflected projection inputs, on Redis list semantics."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from fastamu.messaging.projections.repair.queue import RedisFailureQueue
from fastamu.messaging.projections.repair.records import FailureRecord


class FakeRedis:
    """The four list commands the queue uses, with Redis semantics."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key: str, *values: Any) -> int:
        self.lists.setdefault(key, []).extend(str(value) for value in values)
        return len(self.lists[key])

    async def lpop(self, key: str, count: int | None = None) -> Any:
        items = self.lists.get(key, [])
        if not items:
            return None
        if count is None:
            return items.pop(0)
        taken = items[:count]
        del items[:count]
        return taken

    async def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        items = self.lists.get(key, [])
        self.lists[key] = (
            items[start:] if end == -1 else items[start : end + 1]
        )
        return True


def make_queue(
    max_attempts: int = 5,
    max_pending: int = 100_000,
) -> tuple[RedisFailureQueue, FakeRedis]:
    fake = FakeRedis()
    queue = RedisFailureQueue(
        SimpleNamespace(client=fake),  # type: ignore[arg-type]
        "failures",
        max_attempts,
        max_pending,
    )
    return queue, fake


async def test_records_are_taken_in_order_and_only_once() -> None:
    queue, _ = make_queue()
    await queue.record("products", [7, 8, 9], "failed")

    first = await queue.take("products", 2)
    second = await queue.take("products", 2)

    assert [record.input_id for record in first] == [7, 8]
    assert [record.input_id for record in second] == [9]
    assert await queue.take("products", 2) == []


async def test_each_projection_has_its_own_queue() -> None:
    queue, _ = make_queue()
    await queue.record("products", [7], "failed")
    await queue.record("variants", [9], "failed")

    assert [r.input_id for r in await queue.take("products", 10)] == [7]
    assert [r.input_id for r in await queue.take("variants", 10)] == [9]


async def test_repeated_ids_in_one_failure_are_recorded_once() -> None:
    queue, _ = make_queue()
    await queue.record("products", [7, 7, 8], "failed")

    assert [r.input_id for r in await queue.take("products", 10)] == [7, 8]


async def test_a_handed_back_record_goes_to_the_tail_with_one_attempt() -> (
    None
):
    queue, _ = make_queue()
    await queue.record("products", [7, 8], "failed")
    taken = await queue.take("products", 1)
    await queue.requeue("products", taken)

    rest = await queue.take("products", 10)
    assert [record.input_id for record in rest] == [8, 7]
    assert [record.attempts for record in rest] == [0, 1]


async def test_spending_every_attempt_moves_a_record_to_the_dead_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue, fake = make_queue(max_attempts=2)
    await queue.record("products", [7], "keeps failing")

    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            await queue.requeue("products", await queue.take("products", 10))

    assert await queue.take("products", 10) == []
    dead = fake.lists[queue.dead_key("products")]
    assert [
        FailureRecord.model_validate_json(row).input_id for row in dead
    ] == [7]
    assert "Gave up on 1 products inputs after 2 attempts: 7" in caplog.text


async def test_a_new_failure_of_a_dead_input_is_queued_again() -> None:
    queue, _ = make_queue(max_attempts=1)
    await queue.record("products", [7], "keeps failing")
    await queue.requeue("products", await queue.take("products", 10))
    assert await queue.take("products", 10) == []

    await queue.record("products", [7], "failed again")

    records = await queue.take("products", 10)
    assert [record.input_id for record in records] == [7]
    assert records[0].attempts == 0


async def test_the_queue_drops_its_oldest_over_the_ceiling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue, _ = make_queue(max_pending=3)

    with caplog.at_level(logging.WARNING):
        await queue.record("products", [1, 2, 3, 4, 5], "failed")

    records = await queue.take("products", 10)
    assert [record.input_id for record in records] == [3, 4, 5]
    assert "Dropped 2 oldest products failures" in caplog.text


async def test_nothing_is_written_for_an_empty_call() -> None:
    queue, fake = make_queue()

    await queue.record("products", [], "failed")
    await queue.requeue("products", [])

    assert fake.lists == {}
    assert await queue.take("products", 0) == []
