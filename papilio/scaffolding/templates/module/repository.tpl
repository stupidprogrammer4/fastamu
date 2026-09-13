from papilio.infra.db.repositories.backends.postgresql import (
    PostgreSQLIdentifiedRepository,
)
from <<PKG>>.<<M>>.infra.tables import <<P>>Table
from <<PKG>>.<<M>>.domain.entities import <<P>>Model


class <<P>>Repository(PostgreSQLIdentifiedRepository[<<P>>Model]):
    table = <<P>>Table
