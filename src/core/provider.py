
from typing import AsyncIterable, AsyncIterator

from dishka import Provider, Scope, provide
from taskiq import ScheduleSource
from taskiq_redis import RedisScheduleSource

from src.infra.postgres.connection import PGConnection
from src.infra.postgres.uow import PGUnitOfWork
from src.infra.es.client import ESClient
from src.infra.redis.client import RedisClient

from src.core.config import Settings, get_settings


class CoreProvider(Provider):

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return get_settings()
    
    @provide(scope=Scope.APP)
    def postgresql(self, settings: Settings) -> PGConnection:
        return PGConnection(
            dsn=settings.postgresql.dsn,
            pool_size=settings.postgresql.pool_size,
            max_overflow=settings.postgresql.max_overflow,
            pool_timeout=settings.postgresql.pool_timeout,
            pool_recycle=settings.postgresql.pool_recycle
        )

    @provide(scope=Scope.REQUEST)
    async def uow(self, pg: PGConnection) -> AsyncIterable[PGUnitOfWork]:
        async with PGUnitOfWork(pg) as uow:
            yield uow
        
    
    @provide(scope=Scope.APP)
    async def es(self, settings: Settings) -> AsyncIterator[ESClient]:
        client = ESClient(
            settings.es.hosts,
            username=settings.es.username,
            password=settings.es.password,
            api_key=settings.es.api_key,
            verify_certs=settings.es.verify_certs,
            ca_certs=settings.es.ca_certs,
        )
        try:
            yield client
        finally:
            await client.close()


    @provide(scope=Scope.APP)
    def schedule_source(self, settings: Settings) -> ScheduleSource:
        return RedisScheduleSource(
            url=settings.taskiq.redis_url,
            max_connection_pool_size=settings.taskiq.max_connection_pool_size,
        )

    @provide(scope=Scope.APP)
    async def redis(self, settings: Settings) -> AsyncIterator[RedisClient]:
        client = RedisClient(
            settings.redis.url,
            max_connections=settings.redis.max_connections,
            socket_timeout=settings.redis.socket_timeout,
            socket_connect_timeout=settings.redis.socket_connect_timeout,
            health_check_interval=settings.redis.health_check_interval,
        )
        try:
            yield client
        finally:
            await client.close()