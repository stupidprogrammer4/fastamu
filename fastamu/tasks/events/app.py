"""Event consumer entrypoint: faststream run fastamu.tasks.events.app:app."""

from dishka import make_async_container
from dishka_faststream import FastStreamProvider, setup_dishka
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitRouter
from faststream.redis import RedisBroker, RedisRouter

from fastamu.core.bootstrap import get_bootstrapper
from fastamu.core.provider import CoreProvider
from fastamu.tasks.events.broker import broker


def create_app() -> FastStream:
    bootstrapper = get_bootstrapper()
    providers = bootstrapper.boot_providers()
    routers = [
        *bootstrapper.boot_subscribers(),
        *bootstrapper.boot_publishers(),
    ]
    seen: set[int] = set()
    for router in routers:
        if id(router) in seen:
            continue
        if isinstance(broker, RabbitBroker) and isinstance(
            router, RabbitRouter
        ):
            broker.include_router(router)
        elif isinstance(broker, RedisBroker) and isinstance(
            router, RedisRouter
        ):
            broker.include_router(router)
        else:
            raise TypeError(
                "Discovered router does not match the event broker"
            )
        seen.add(id(router))
    container = make_async_container(
        FastStreamProvider(), CoreProvider(), *providers
    )
    app = FastStream(broker)
    setup_dishka(container, app=app, finalize_container=True)
    return app


app = create_app()
