from typing import Any

from sqlalchemy import case, inspect, literal, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import Insert


class DatabaseDialect:
    """Only SQL semantics that differ between database families live here."""

    name = "generic"
    returning = False

    def unique_values(self, error: IntegrityError) -> dict[str, Any] | None:
        return None

    def insert_if_absent(self, table, values, keys) -> Insert | None:
        return None

    def upsert(self, table, rows, keys):
        raise NotImplementedError(
            f"Atomic upsert is not implemented for {self.name}"
        )

    def values_grid(self, table, rows):
        raise NotImplementedError(
            f"VALUES grids are not supported for {self.name}"
        )

    def bulk_update(self, table, rows, key, managed):
        names = [name for name in rows[0] if name not in managed | {key}]
        columns = inspect(table).columns
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
