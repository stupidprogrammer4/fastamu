from asyncio import CancelledError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastamu.infra.db.uow import DBUnitOfWork


@pytest.fixture
async def unit():
    session = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        close=AsyncMock(),
        in_nested_transaction=lambda: False,
    )
    unit = DBUnitOfWork(SimpleNamespace(session_factory=lambda: session))
    await unit.begin()
    try:
        yield unit
    finally:
        await unit.close()


async def test_runs_after_successful_commit_once(unit):
    calls = []
    unit.session.commit.side_effect = lambda: calls.append("commit")

    async def callback():
        calls.append("callback")

    await DBUnitOfWork.on_commit(callback)
    assert calls == []
    await unit.commit()
    await unit.commit()
    assert calls == ["commit", "callback", "commit"]


@pytest.mark.parametrize("failure", ["rollback", "commit", "close"])
async def test_abandoned_transaction_discards_callbacks(unit, failure):
    callback = AsyncMock()
    await DBUnitOfWork.on_commit(callback)
    if failure == "commit":
        unit.session.commit.side_effect = RuntimeError("commit failed")
        with pytest.raises(RuntimeError):
            await unit.commit()
        unit.session.commit.side_effect = None
    elif failure == "close":
        await unit.close()
        await unit.begin()
    else:
        await unit.rollback()
    await unit.commit()
    callback.assert_not_awaited()


async def test_failed_rollback_also_discards_callbacks(unit):
    callback = AsyncMock()
    await DBUnitOfWork.on_commit(callback)
    unit.session.rollback.side_effect = RuntimeError("rollback failed")
    with pytest.raises(RuntimeError):
        await unit.rollback()
    await unit.commit()
    callback.assert_not_awaited()


async def test_callback_failure_does_not_skip_other_callbacks_or_replay(unit):
    failing = AsyncMock(side_effect=ValueError("Redis unavailable"))
    remaining = AsyncMock()
    await DBUnitOfWork.on_commit(failing)
    await DBUnitOfWork.on_commit(remaining)
    with pytest.raises(ExceptionGroup) as caught:
        await unit.commit()
    assert isinstance(caught.value.exceptions[0], ValueError)
    remaining.assert_awaited_once()
    await unit.commit()
    failing.assert_awaited_once()
    remaining.assert_awaited_once()


async def test_repeated_key_replaces_only_that_operation(unit):
    first = AsyncMock()
    second = AsyncMock()
    await DBUnitOfWork.on_commit(first, key="product:1")
    await DBUnitOfWork.on_commit(second, key="product:1")
    await unit.commit()
    first.assert_not_awaited()
    second.assert_awaited_once()


async def test_without_uow_runs_immediately():
    callback = AsyncMock()
    await DBUnitOfWork.on_commit(callback)
    callback.assert_awaited_once()


async def test_cancelled_commit_discards_callbacks(unit):
    callback = AsyncMock()
    await DBUnitOfWork.on_commit(callback)
    unit.session.commit.side_effect = CancelledError()
    with pytest.raises(CancelledError):
        await unit.commit()
    unit.session.commit.side_effect = None
    await unit.commit()
    callback.assert_not_awaited()
