from .base import DatabaseDialect


class MySQLDialect(DatabaseDialect):
    name = "mysql"

    def unique_values(self, error):
        args = getattr(error.orig, "args", ())
        # MySQL reports an index name, not a reliable mapping of column values.
        return {} if args and args[0] == 1062 else None
