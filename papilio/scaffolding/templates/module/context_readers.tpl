from papilio.infra.db.repositories.backends.postgresql import (
    PostgreSQLReader,
)
from <<PKG>>.<<M>>.domain.context import <<P>>Context


class <<P>>Reader(PostgreSQLReader):
    """Reads the specific columns the <<S>> logic runs on — nothing more.

    It owns no table: one statement selects exactly the fields it needs and
    returns them as a <<P>>Context.
    """

    async def read(self) -> <<P>>Context:
        raise NotImplementedError
