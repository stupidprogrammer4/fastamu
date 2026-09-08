from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastamu.infra.db.uow import DBUnitOfWork


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
