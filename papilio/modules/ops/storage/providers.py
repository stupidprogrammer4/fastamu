from dishka import Provider, Scope, provide

from papilio.core.config import Settings, StorageConfig
from papilio.modules.ops.storage.app.services import MediaService
from papilio.modules.ops.storage.infra.repository import MediaRepository
from papilio.modules.ops.storage.infra.storage import LocalStorage
from papilio.modules.ops.storage.interfaces import IMediaService


class StorageProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def storage_config(self, settings: Settings) -> StorageConfig:
        return settings.storage

    @provide
    def local_storage(self, config: StorageConfig) -> LocalStorage:
        return LocalStorage(config.path)

    media_repo = provide(MediaRepository)

    media_service = provide(MediaService, provides=IMediaService)
