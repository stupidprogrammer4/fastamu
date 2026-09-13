from typing import Any

from sqlalchemy.exc import IntegrityError


class DatabaseDialect:
    name = "generic"

    def unique_values(self, error: IntegrityError) -> dict[str, Any] | None:
        return None
