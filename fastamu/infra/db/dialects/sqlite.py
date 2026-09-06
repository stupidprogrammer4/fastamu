from sqlalchemy.dialects.sqlite import insert

from .base import DatabaseDialect


class SQLiteDialect(DatabaseDialect):
    name = "sqlite"
    returning = True  # SQLite >= 3.35

    def unique_values(self, error):
        code = getattr(error.orig, "sqlite_errorcode", None)
        return {} if code in (1555, 2067) else None

    def upsert(self, table, rows, keys):
        stmt = insert(table).values(rows)
        changes = {
            name: stmt.excluded[name] for name in rows[0] if name not in keys
        }
        if not changes:
            changes = {keys[0]: stmt.excluded[keys[0]]}
        return stmt.on_conflict_do_update(index_elements=keys, set_=changes)
