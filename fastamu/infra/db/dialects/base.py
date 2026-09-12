from typing import Any

from sqlalchemy import case, inspect, literal, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Insert

from fastamu.infra.db.uow import DBUnitOfWork, FetchUnitOfWork


class DatabaseDialect:
    """Only SQL semantics that differ between database families live here."""

    name = "generic"
    uow: type[DBUnitOfWork] = FetchUnitOfWork

    def unique_values(self, error: IntegrityError) -> dict[str, Any] | None:
        return None

    def insert_if_absent(self, table, values, keys) -> Insert | None:
        return None

    def upsert(self, table, rows, keys):
        raise NotImplementedError(
            f"Atomic upsert is not implemented for {self.name}"
        )

    def onupdate_changes(self, table, changes):
        """An upsert's SET clause is supplied, so ``onupdate`` misses it."""
        return {
            column.key: (
                column.onupdate.arg(None)
                if column.onupdate.is_callable
                else column.onupdate.arg
            )
            for column in inspect(table).columns
            if column.onupdate is not None and column.key not in changes
        }

    def values_grid(self, table, rows):
        raise NotImplementedError(
            f"VALUES grids are not supported for {self.name}"
        )

    def bulk_update(self, table, rows, key):
        columns = inspect(table).columns
        # a column the database writes on update is not the caller's to send
        names = [
            name
            for name in rows[0]
            if name != key and columns[name].onupdate is None
        ]
        return (
            update(table)
            .where(getattr(table, key).in_([r[key] for r in rows]))
            .values(
                {
                    name: case(
                        *(
                            (
                                getattr(table, key) == row[key],
                                literal(row[name], type_=columns[name].type),
                            )
                            for row in rows
                        ),
                        else_=getattr(table, name),
                    )
                    for name in names
                }
            )
        )
