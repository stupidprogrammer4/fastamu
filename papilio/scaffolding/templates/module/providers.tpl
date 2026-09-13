from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.repository import <<P>>Repository
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
