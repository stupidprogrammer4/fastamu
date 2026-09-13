from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.readers import <<P>>Reader
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_reader = provide(<<P>>Reader)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)
