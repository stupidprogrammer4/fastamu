"""Optional typed database providers; applications select the backend."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from papilio.core.config import DatabaseConfig
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import (
    MariaDBUnitOfWork,
    MSSQLUnitOfWork,
    MySQLUnitOfWork,
    OracleUnitOfWork,
    PGUnitOfWork,
    SQLiteUnitOfWork,
    UnitOfWork,
)


class DBProvider[U: UnitOfWork](Provider):
    """Shared connection lifetime with typed registrations in subclasses."""

    uow_type: type[U]

    def __init__(self, config: DatabaseConfig) -> None:
        super().__init__()
        self.config = config

    @asynccontextmanager
    async def _database(self) -> AsyncGenerator[DBConnection[U]]:
        database = DBConnection(
            uow_factory=self.uow_type,
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


class PGProvider(DBProvider[PGUnitOfWork]):
    uow_type = PGUnitOfWork

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncGenerator[DBConnection[PGUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[PGUnitOfWork]
    ) -> AsyncGenerator[PGUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: PGUnitOfWork) -> AsyncSession:
        return uow.session


class MySQLProvider(DBProvider[MySQLUnitOfWork]):
    uow_type = MySQLUnitOfWork

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncGenerator[DBConnection[MySQLUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[MySQLUnitOfWork]
    ) -> AsyncGenerator[MySQLUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: MySQLUnitOfWork) -> AsyncSession:
        return uow.session


class MariaDBProvider(DBProvider[MariaDBUnitOfWork]):
    uow_type = MariaDBUnitOfWork

    @provide(scope=Scope.APP)
    async def database(
        self,
    ) -> AsyncGenerator[DBConnection[MariaDBUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[MariaDBUnitOfWork]
    ) -> AsyncGenerator[MariaDBUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: MariaDBUnitOfWork) -> AsyncSession:
        return uow.session


class SQLiteProvider(DBProvider[SQLiteUnitOfWork]):
    uow_type = SQLiteUnitOfWork

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncGenerator[DBConnection[SQLiteUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[SQLiteUnitOfWork]
    ) -> AsyncGenerator[SQLiteUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: SQLiteUnitOfWork) -> AsyncSession:
        return uow.session


class OracleProvider(DBProvider[OracleUnitOfWork]):
    uow_type = OracleUnitOfWork

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncGenerator[DBConnection[OracleUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[OracleUnitOfWork]
    ) -> AsyncGenerator[OracleUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: OracleUnitOfWork) -> AsyncSession:
        return uow.session


class MSSQLProvider(DBProvider[MSSQLUnitOfWork]):
    uow_type = MSSQLUnitOfWork

    @provide(scope=Scope.APP)
    async def database(self) -> AsyncGenerator[DBConnection[MSSQLUnitOfWork]]:
        async with self._database() as database:
            yield database

    @provide(scope=Scope.REQUEST)
    async def uow(
        self, connection: DBConnection[MSSQLUnitOfWork]
    ) -> AsyncGenerator[MSSQLUnitOfWork]:
        async with connection.uow() as unit:
            yield unit

    @provide(scope=Scope.REQUEST)
    def session(self, uow: MSSQLUnitOfWork) -> AsyncSession:
        return uow.session
