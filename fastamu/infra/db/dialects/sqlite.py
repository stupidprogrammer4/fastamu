from .base import DatabaseDialect


class SQLiteDialect(DatabaseDialect):
    name = "sqlite"

    def unique_values(self, error):
        code = getattr(error.orig, "sqlite_errorcode", None)
        return {} if code in (1555, 2067) else None
