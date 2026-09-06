import re
from typing import Any, Unpack

from sqlalchemy import (
    BigInteger,
    Column,
    Index,
    column,
    inspect,
    literal,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert
from sqlmodel import Field

from fastamu.common.models.fields import (
    ColumnKwargs,
    _field,
    _model_defaults,
)

from .base import DatabaseDialect


class PostgreSQLDialect(DatabaseDialect):
    name = "postgresql"
    returning = True

    def unique_values(self, error):
        cause = getattr(error.orig, "__cause__", None) or error.orig
        if getattr(cause, "sqlstate", None) != "23505":
            return None
        detail = getattr(cause, "detail", None)
        if detail is None:
            detail = getattr(
                getattr(cause, "diag", None), "message_detail", ""
            )
        found = re.match(r"Key \((.+)\)=\((.+)\) already exists", detail or "")
        if found is None:
            return {}
        return dict(
            zip(
                (name.strip() for name in found.group(1).split(",")),
                (value.strip() for value in found.group(2).split(",")),
            )
        )

    def upsert(self, table, rows, keys):
        stmt = insert(table).values(rows)
        changes = {
            name: stmt.excluded[name] for name in rows[0] if name not in keys
        }
        if not changes:
            changes = {keys[0]: stmt.excluded[keys[0]]}
        return stmt.on_conflict_do_update(index_elements=keys, set_=changes)

    def values_grid(self, table, rows):
        mapper = inspect(table)
        names = list(rows[0])
        types = {name: mapper.columns[name].type for name in names}
        return values(
            *(column(name, types[name]) for name in names), name="bulk_values"
        ).data(
            [
                tuple(literal(row[name], types[name]) for name in names)
                for row in rows
            ]
        )

    def bulk_update(self, table, rows, key, managed):
        grid = self.values_grid(table, rows)
        return (
            update(table)
            .where(getattr(table, key) == grid.c[key])
            .values(
                {
                    name: grid.c[name]
                    for name in grid.c.keys()
                    if name not in managed | {key}
                }
            )
        )


def JSONBField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(JSONB, **kwargs)


def ArrayField(
    item_type: Any = BigInteger,
    *,
    gin_index: str | None = None,
    **kwargs: Unpack[ColumnKwargs],
) -> Any:
    kwargs.setdefault("nullable", False)
    defaults = _model_defaults(kwargs)
    if "server_default" in kwargs and not kwargs.get("nullable"):
        defaults = {"default_factory": list}
    column = Column(ARRAY(item_type), **kwargs)
    if gin_index:
        Index(gin_index, column, postgresql_using="gin")
    if "default_factory" in defaults:
        return Field(
            default_factory=defaults["default_factory"], sa_column=column
        )
    if "default" in defaults:
        return Field(default=defaults["default"], sa_column=column)
    return Field(sa_column=column)


async def reset_schema(connection):
    from sqlalchemy import text

    await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    await connection.execute(text("CREATE SCHEMA public"))


async def truncate_tables(session, tables):
    from sqlalchemy import text

    preparer = session.get_bind().dialect.identifier_preparer
    names = ", ".join(preparer.format_table(table) for table in tables)
    await session.execute(
        text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    )
