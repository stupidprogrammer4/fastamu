from typing import TYPE_CHECKING, Any

from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fastamu.infra.db.dialects import DatabaseDialect, get_dialect

if TYPE_CHECKING:
    from fastamu.infra.db.uow import DBUnitOfWork


class DBConnection:
    def __init__(
        self,
        dsn: str,
        pool_size: int,
        max_overflow: int,
        pool_timeout: int,
        pool_recycle: int,
    ) -> None:
        url = make_url(dsn)
        options: dict[str, Any] = {"pool_recycle": pool_recycle}
        if url.get_backend_name() == "sqlite":
            # Python 3.13: savepoints must belong to a real outer transaction.
            options["connect_args"] = {"autocommit": False}
        # In-memory SQLite uses StaticPool, which has no queue-pool options.
        if not (
            url.get_backend_name() == "sqlite"
            and url.database in (None, "", ":memory:")
        ):
            options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
            )
        self.engine = create_async_engine(url, **options)
        self.adapter: DatabaseDialect = get_dialect(url.get_backend_name())
        self.uow_factory = self.adapter.uow
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            autocommit=False,
        )

    def uow(self) -> "DBUnitOfWork":
        """Open a unit of work that knows how to write on this database."""
        return self.uow_factory(self)

    @property
    def dialect(self) -> Dialect:
        """The actual SQLAlchemy dialect, including driver capabilities."""
        return self.engine.dialect

    async def dispose(self) -> None:
        await self.engine.dispose()
