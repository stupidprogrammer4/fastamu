from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    service = provide(<<P>>Service, provides=I<<P>>Service, scope=Scope.REQUEST)
