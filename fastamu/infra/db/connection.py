from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
        options = {"pool_recycle": pool_recycle}
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
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            autocommit=False,
        )

    @property
    def dialect(self) -> Dialect:
        """The actual SQLAlchemy dialect, including driver capabilities."""
        return self.engine.dialect

    async def dispose(self) -> None:
        await self.engine.dispose()
