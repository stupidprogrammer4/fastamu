from papilio.infra.es.repository import ESRepository
from papilio.infra.db.repositories.backends.postgresql import (
    PGIdentifiedRepository,
)
from <<PKG>>.<<M>>.infra.tables import <<P>>Table
from <<PKG>>.<<M>>.domain.documents import <<P>>Document
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Repository(PGIdentifiedRepository[<<P>>Model]):
    table = <<P>>Table


class <<P>>ESRepository(ESRepository[<<P>>Document]): ...
