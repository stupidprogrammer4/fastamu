from dishka import Provider, Scope, provide

from <<PKG>>.<<M>>.app.commands import <<P>>CreateCommand
from <<PKG>>.<<M>>.app.queries import <<P>>SearchQuery
from <<PKG>>.<<M>>.app.services import <<P>>Service
from <<PKG>>.<<M>>.infra.repository import (
    <<P>>ESStore,
    <<P>>Repository,
)
from <<PKG>>.<<M>>.interfaces import I<<P>>Service


class <<P>>Provider(Provider):
    scope = Scope.REQUEST

    <<S>>_repo = provide(<<P>>Repository)
    <<S>>_es_store = provide(<<P>>ESStore)
    <<S>>_service = provide(<<P>>Service, provides=I<<P>>Service)

    create_command = provide(<<P>>CreateCommand)
    search_query = provide(<<P>>SearchQuery)
