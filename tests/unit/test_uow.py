from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastamu.infra.db.uow import DBUnitOfWork


async def test_scope_only_opens_and_closes_session():
    session = SimpleNamespace(
        commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock()
    )
    unit = DBUnitOfWork(SimpleNamespace(session_factory=lambda: session))
    async with unit:
        assert unit.session is session
        assert DBUnitOfWork.current() is unit
    session.commit.assert_not_awaited()
    session.close.assert_awaited_once()
    assert DBUnitOfWork.current() is None
    with pytest.raises(RuntimeError, match="not open"):
        _ = unit.session


async def test_close_failure_still_clears_context():
    session = SimpleNamespace(
        close=AsyncMock(side_effect=RuntimeError("close"))
    )
    unit = DBUnitOfWork(SimpleNamespace(session_factory=lambda: session))
    with pytest.raises(RuntimeError, match="close"):
        async with unit:
            pass
    assert unit._session is None
    assert DBUnitOfWork.current() is None


async def test_open_twice_is_rejected_and_close_is_idempotent():
    session = SimpleNamespace(close=AsyncMock())
    unit = DBUnitOfWork(SimpleNamespace(session_factory=lambda: session))
    async with unit:
        with pytest.raises(RuntimeError, match="already open"):
            await unit.begin()
    await unit.close()
    session.close.assert_awaited_once()
