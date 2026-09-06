from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastamu.infra.db.uow import DBUnitOfWork, after_commit


async def test_after_commit_runs_only_after_a_successful_commit() -> None:
    seen = []

    async def commit() -> None:
        seen.append("commit")

    async def publish() -> None:
        seen.append("publish")

    unit = DBUnitOfWork(None)
    unit._session = SimpleNamespace(info={}, commit=commit)
    after_commit(unit.session, publish)

    await unit.commit()

    assert seen == ["commit", "publish"]


async def test_rollback_discards_after_commit_work() -> None:
    publish = AsyncMock()
    unit = DBUnitOfWork(None)
    unit._session = SimpleNamespace(info={}, rollback=AsyncMock())
    after_commit(unit.session, publish)

    await unit.rollback()

    publish.assert_not_awaited()
    assert unit.session.info == {}


@pytest.mark.parametrize("failure", ["commit", "rollback"])
async def test_transaction_failure_still_closes_the_session(
    failure: str,
) -> None:
    session = SimpleNamespace(
        info={}, commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock()
    )
    getattr(session, failure).side_effect = RuntimeError(failure)
    unit = DBUnitOfWork(None)
    unit._session = session
    error = (
        RuntimeError("application failed") if failure == "rollback" else None
    )

    with pytest.raises(RuntimeError, match=failure):
        await unit.__aexit__(type(error) if error else None, error, None)

    session.close.assert_awaited_once()
    assert unit._session is None
