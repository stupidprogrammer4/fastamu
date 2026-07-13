
from datetime import datetime

from sqlalchemy import text

from src.infra.postgres.connection import PGConnection


class PGUnitOfWork:
    def __init__(self, pg: PGConnection):
        self.pg = pg
        self._session = None

    @property
    def session(self):
        if not self._session:
            raise RuntimeError("Session not initialized. Use 'async with' or call 'begin()' first.")
        return self._session

    async def begin(self):
        self._session = self.pg.session_factory()
        return self
    
    async def close(self):
        await self.session.close()
        self._session = None
    
    async def commit(self):
        await self.session.commit()
    
    async def rollback(self):
        await self.session.rollback()

    async def now(self) -> datetime:
        result = await self.session.execute(text("SELECT NOW()"))
        return result.scalar_one()

    async def __aenter__(self):
        session = await self.begin()
        return session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self.close()