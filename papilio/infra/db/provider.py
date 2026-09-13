from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from papilio.core.config import DatabaseConfig
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import PostgreSQLUnitOfWork


class PostgreSQLProvider(Provider):
    def __init__(self, config: DatabaseConfig) -> None:
        super().__init__()
        self.config = config

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[PostgreSQLUnitOfWork]
    ) -> AsyncIterator[PostgreSQLUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: PostgreSQLUnitOfWork) -> AsyncSession:
        return uow.session

    @provide(scope=Scope.APP)
    async def database(
        self,
    ) -> AsyncIterator[DBConnection[PostgreSQLUnitOfWork]]:
        database = DBConnection(
            uow_factory=PostgreSQLUnitOfWork,
            dsn=self.config.dsn,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_recycle=self.config.pool_recycle,
        )
        try:
            yield database
        finally:
            await database.dispose()
