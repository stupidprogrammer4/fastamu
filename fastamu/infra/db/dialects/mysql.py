from sqlalchemy.dialects.mysql import insert

from .base import DatabaseDialect


class MySQLDialect(DatabaseDialect):
    name = "mysql"

    def unique_values(self, error):
        args = getattr(error.orig, "args", ())
        # MySQL reports an index name, not a reliable mapping of column values.
        return {} if args and args[0] == 1062 else None

    def upsert(self, table, rows, keys):
        stmt = insert(table).values(rows)
        changes = {
            name: stmt.inserted[name] for name in rows[0] if name not in keys
        }
        if not changes:
            changes = {keys[0]: stmt.inserted[keys[0]]}
        changes.update(self.onupdate_changes(table, changes))
        return stmt.on_duplicate_key_update(**changes)
