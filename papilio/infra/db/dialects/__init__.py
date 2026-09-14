"""Adapters for SQLAlchemy's built-in relational database families."""

from .base import DatabaseDialect
from .mariadb import MariaDBDialect
from .mssql import MSSQLDialect
from .mysql import MySQLDialect
from .oracle import OracleDialect
from .postgresql import PGDialect
from .sqlite import SQLiteDialect

DIALECTS: dict[str, type[DatabaseDialect]] = {
    dialect.name: dialect
    for dialect in (
        PGDialect,
        MySQLDialect,
        MariaDBDialect,
        SQLiteDialect,
        MSSQLDialect,
        OracleDialect,
    )
}


def get_dialect(name: str) -> DatabaseDialect:
    try:
        return DIALECTS[name]()
    except KeyError:
        raise NotImplementedError(
            f"No Papilio database adapter for {name}"
        ) from None
