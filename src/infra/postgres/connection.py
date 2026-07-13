from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker


class PGConnection:
    def __init__(
        self,
        dsn: str,
        pool_size: int,
        max_overflow: int,
        pool_timeout: int,
        pool_recycle: int,
    ) -> None:
        self.engine = create_async_engine(
            dsn,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            autocommit=False
        )
    
    async def dispose(self) -> None:
        await self.engine.dispose()