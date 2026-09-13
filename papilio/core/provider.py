from dishka import Provider, Scope, provide

from papilio.core.config import Settings, get_settings
from papilio.security.passwords import PasswordHasher


class CoreProvider(Provider):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return self._settings if self._settings is not None else get_settings()

    @provide(scope=Scope.APP)
    def password_hasher(self, settings: Settings) -> PasswordHasher:
        return PasswordHasher(settings.crypto.password_salt)
