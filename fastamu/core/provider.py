from typing import AsyncIterable, AsyncIterator

from dishka import Provider, Scope, provide
from taskiq import ScheduleSource

from fastamu.common.security.passwords import PasswordHasher
from fastamu.core.config import Settings, get_settings
from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.infra.es.client import ESClient
from fastamu.infra.http.connection import HTTPConnection
from fastamu.infra.redis.client import RedisClient


class CoreProvider(Provider):
    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return get_settings()

    @provide(scope=Scope.APP)
    def password_hasher(self, settings: Settings) -> PasswordHasher:
        return PasswordHasher(settings.crypto.password_salt)

    @provide(scope=Scope.APP)
    def database(self, settings: Settings) -> DBConnection:
        return DBConnection(
            dsn=settings.db.dsn,
            pool_size=settings.db.pool_size,
            max_overflow=settings.db.max_overflow,
            pool_timeout=settings.db.pool_timeout,
            pool_recycle=settings.db.pool_recycle,
        )

    @provide(scope=Scope.REQUEST)
    async def uow(self, pg: DBConnection) -> AsyncIterable[DBUnitOfWork]:
        async with DBUnitOfWork(pg) as uow:
            yield uow

    @provide(scope=Scope.APP)
    async def es(self, settings: Settings) -> AsyncIterator[ESClient]:
        if settings.es is None:
            raise RuntimeError("Elasticsearch is disabled; configure es")
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
        from taskiq_redis import RedisScheduleSource

        if settings.tasks.schedulers is None:
            raise RuntimeError("Scheduler is disabled")
        return RedisScheduleSource(
            url=settings.tasks.schedulers.url,
            max_connection_pool_size=settings.tasks.schedulers.max_connection_pool_size,
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

    @provide(scope=Scope.APP)
    async def http(self, settings: Settings) -> AsyncIterator[HTTPConnection]:
        connection = HTTPConnection(
            max_connections=settings.http.max_connections,
            max_keepalive_connections=settings.http.max_keepalive_connections,
            keepalive_expiry=settings.http.keepalive_expiry,
            timeout=settings.http.timeout,
            connect_timeout=settings.http.connect_timeout,
            follow_redirects=settings.http.follow_redirects,
        )
        try:
            yield connection
        finally:
            await connection.close()
