from dishka import Provider, Scope, provide

from papilio.security.passwords import PasswordHasher


class PasswordProvider(Provider):
    def __init__(self, salt: str) -> None:
        super().__init__()
        self.salt = salt

    @provide(scope=Scope.APP)
    def hasher(self) -> PasswordHasher:
        return PasswordHasher(self.salt)
