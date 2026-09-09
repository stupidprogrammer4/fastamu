import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pamqp.commands import Basic

from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.tasks.projection.recovery import publish_confirmed


@pytest.mark.parametrize(
    "confirmation", [None, False, True, object(), Basic.Nack()]
)
async def test_truthy_non_ack_is_not_publication_confirmation(confirmation):
    channel = SimpleNamespace(
        default_exchange=SimpleNamespace(
            publish=AsyncMock(return_value=confirmation)
        )
    )
    with pytest.raises(RuntimeError, match="did not confirm"):
        await publish_confirmed(channel, "queue", b"body")


async def test_nested_units_restore_context_and_parallel_tasks_are_isolated():
    db = SimpleNamespace(
        session_factory=lambda: SimpleNamespace(
            close=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock()
        )
    )
    initial = DBUnitOfWork.current()
    async with DBUnitOfWork(db) as outer:

        async def child():
            async with DBUnitOfWork(db) as inner:
                await asyncio.sleep(0)
                assert DBUnitOfWork.current() is inner
            assert DBUnitOfWork.current() is outer

        await asyncio.gather(child(), child())
        assert DBUnitOfWork.current() is outer
    assert DBUnitOfWork.current() is initial


async def test_standalone_projection_has_no_version_ticket():
    assert await DBUnitOfWork.stage_projection(object, [7], 12345) is None
