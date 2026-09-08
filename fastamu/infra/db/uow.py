from datetime import datetime

from sqlalchemy import func, select

from fastamu.infra.db.connection import DBConnection


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

    async def rollback(self):
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


class Rollback:
    pass


async def rollback_transaction(uow: DBUnitOfWork) -> Rollback:
    """Roll back the current transaction before resolving the dependency."""
    await uow.rollback()
    return Rollback()
