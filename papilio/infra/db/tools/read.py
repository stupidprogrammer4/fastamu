"""Standalone paging and streaming helpers for scalar/model queries."""

from collections.abc import AsyncIterator

from sqlalchemy import Select, func, select

from papilio.infra.db.uow import UnitOfWork
from papilio.schemas.results import PagedType


async def fetch_page[T](
    uow: UnitOfWork,
    query: Select[tuple[T]],
    *,
    limit: int,
    offset: int = 0,
) -> PagedType[T]:
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset nonnegative")
    query = query.limit(None).offset(None)
    stmt = select(func.count()).select_from(query.order_by(None).subquery())
    result = await uow.execute(stmt)
    total = result.scalar_one()
    stmt = query.limit(limit).offset(offset)
    result = await uow.execute(stmt)
    return PagedType(items=result.scalars().all(), total_items=total or 0)


async def stream[T](
    uow: UnitOfWork,
    query: Select[tuple[T]],
    *,
    batch_size: int = 100,
) -> AsyncIterator[T]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    stmt = query.execution_options(yield_per=batch_size)
    result = await uow.stream(stmt)
    try:
        async for item in result.scalars():
            yield item
    finally:
        await result.close()
