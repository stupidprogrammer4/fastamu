from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import func, select

from fastamu.infra.db.connection import DBConnection

_AFTER_COMMIT = "fastamu_after_commit"


def after_commit(
    session,
    callback: Callable[[], Awaitable[None]],
) -> None:
    """Register work that must run only after this session commits."""
    session.info.setdefault(_AFTER_COMMIT, []).append(callback)


class DBUnitOfWork:
    def __init__(self, db: DBConnection):
        self.db = db
        self._session = None

    @property
    def session(self):
        if not self._session:
            raise RuntimeError(
                "Session not initialized. "
                "Use 'async with' or call 'begin()' first."
            )
        return self._session

    async def begin(self):
        self._session = self.db.session_factory()
        return self

    async def close(self):
        await self.session.close()
        self._session = None

    async def commit(self):
        await self.session.commit()
        callbacks = self.session.info.pop(_AFTER_COMMIT, [])
        for callback in callbacks:
            await callback()

    async def rollback(self):
        self.session.info.pop(_AFTER_COMMIT, None)
        await self.session.rollback()

    async def now(self) -> datetime:
        result = await self.session.execute(select(func.current_timestamp()))
        return result.scalar_one()

    async def __aenter__(self):
        session = await self.begin()
        return session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                await self.rollback()
            else:
                await self.commit()
        finally:
            await self.close()
