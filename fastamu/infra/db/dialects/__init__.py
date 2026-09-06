"""Adapters for SQLAlchemy's built-in relational database families."""

from .base import DatabaseDialect
from .mariadb import MariaDBDialect
from .mssql import MSSQLDialect
from .mysql import MySQLDialect
from .oracle import OracleDialect
from .postgresql import PostgreSQLDialect
from .sqlite import SQLiteDialect

DIALECTS: dict[str, type[DatabaseDialect]] = {
    dialect.name: dialect
    for dialect in (
        PostgreSQLDialect,
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
            f"No Fastamu database adapter for {name}"
        ) from None
