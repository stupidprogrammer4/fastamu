from papilio.infra.db.repositories.backends.postgresql import (
    PGIdentifiedRepository,
)
from <<PKG>>.<<M>>.infra.tables import <<P>>Table
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Repository(PGIdentifiedRepository[<<P>>Model]):
    table = <<P>>Table
