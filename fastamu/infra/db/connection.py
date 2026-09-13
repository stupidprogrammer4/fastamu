from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fastamu.infra.db.uow import UnitOfWork


class DBConnection[U: UnitOfWork]:
    def __init__(
        self,
        dsn: str,
        pool_size: int,
        max_overflow: int,
        pool_timeout: int,
        pool_recycle: int,
        *,
        uow_factory: Callable[["DBConnection[U]"], U],
    ) -> None:
        self.uow_factory = uow_factory
        url = make_url(dsn)
        self.backend = url.get_backend_name()
        options: dict[str, Any] = {"pool_recycle": pool_recycle}
        if self.backend == "sqlite":
            # Python 3.13: savepoints must belong to a real outer transaction.
            options["connect_args"] = {"autocommit": False}
        # In-memory SQLite uses StaticPool, which has no queue-pool options.
        if not (
            self.backend == "sqlite" and url.database in (None, "", ":memory:")
        ):
            options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
            )
        self.engine = create_async_engine(url, **options)
        self.backend = url.get_backend_name()
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            close_resets_only=False,
        )

    def uow(self) -> U:
        """Create a fresh unit; its async context opens the session."""
        return self.uow_factory(self)

    @property
    def dialect(self) -> Dialect:
        """The actual SQLAlchemy dialect, including driver capabilities."""
        return self.engine.dialect

    async def dispose(self) -> None:
        await self.engine.dispose()
