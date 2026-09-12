from sqlalchemy.dialects.sqlite import insert

from fastamu.infra.db.uow import ReturningUnitOfWork

from .base import DatabaseDialect


class SQLiteDialect(DatabaseDialect):
    name = "sqlite"
    uow = ReturningUnitOfWork  # SQLite >= 3.35

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
        changes.update(self.onupdate_changes(table, changes))
        return stmt.on_conflict_do_update(index_elements=keys, set_=changes)

    def insert_if_absent(self, table, values, keys):
        return (
            insert(table)
            .values(values)
            .on_conflict_do_nothing(index_elements=keys)
            .returning(*(table.c[key] for key in keys))
        )
