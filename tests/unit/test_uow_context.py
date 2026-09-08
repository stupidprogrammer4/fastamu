import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastamu.common.context import bind_uow, clear_uow, current_uow
from fastamu.common.services import BaseService
from fastamu.infra.db.uow import DBUnitOfWork


class Service(BaseService):
    pass


def bound() -> DBUnitOfWork:
    unit = DBUnitOfWork(None)
    unit._session = SimpleNamespace(info={}, commit=AsyncMock())
    bind_uow(unit)
    return unit


async def test_asking_outside_any_scope_is_refused() -> None:
    clear_uow()

    with pytest.raises(RuntimeError, match="No unit of work is bound"):
        current_uow()


async def test_the_bound_unit_of_work_is_the_one_answered_with() -> None:
    unit = bound()

    assert current_uow() is unit

    clear_uow()


async def test_a_closed_scope_leaves_nothing_bound() -> None:
    bound()

    clear_uow()

    with pytest.raises(RuntimeError, match="No unit of work is bound"):
        current_uow()


async def test_a_service_commits_the_unit_of_work_of_its_scope() -> None:
    unit = bound()

    await Service().commit()

    unit.session.commit.assert_awaited_once()
    clear_uow()


async def test_a_service_outside_a_scope_cannot_commit() -> None:
    clear_uow()

    with pytest.raises(RuntimeError, match="No unit of work is bound"):
        await Service().commit()


async def test_opening_a_unit_of_work_binds_it_to_the_running_task() -> None:
    clear_uow()
    unit = DBUnitOfWork(
        SimpleNamespace(session_factory=lambda: SimpleNamespace(info={}))
    )

    await unit.begin()

    assert current_uow() is unit

    clear_uow()


async def test_two_tasks_each_see_their_own_unit_of_work() -> None:
    clear_uow()
    seen: list[object] = []

    async def open_one() -> None:
        unit = DBUnitOfWork(
            SimpleNamespace(session_factory=lambda: SimpleNamespace(info={}))
        )
        await unit.begin()
        await asyncio.sleep(0)
        seen.append(current_uow() is unit)

    await asyncio.gather(open_one(), open_one())

    assert seen == [True, True]
