from typing import Any

import orjson
from sqlalchemy import JSON, Text
from sqlalchemy.types import TypeDecorator

from .base import DatabaseDialect


class OracleDialect(DatabaseDialect):
    name = "oracle"

    def unique_values(self, error):
        args = getattr(error.orig, "args", ())
        return {} if args and getattr(args[0], "code", None) == 1 else None


# SQLAlchemy 2.0 has no portable native Oracle JSON column type.


class OracleJSON(TypeDecorator[Any]):
    impl = Text
    cache_ok = True

    def __init__(self, *, none_as_null: bool = False):
        super().__init__()
        self.none_as_null = none_as_null
        self.should_evaluate_none = not none_as_null

    def process_bind_param(self, value, dialect):
        if value is JSON.NULL:
            return "null"
        if value is None and self.none_as_null:
            return None
        return orjson.dumps(value).decode("utf-8")

    def process_result_value(self, value, dialect):
        return None if value is None else orjson.loads(value)

    def _cx_oracle_var(self, dialect, cursor, arraysize=1):
        """Allocate a LOB output bind for SQLAlchemy's Oracle RETURNING.

        TypeDecorator hides the driver's LOB implementation from its output
        bind check. An ordinary string variable truncates large JSON results.
        Both Oracle drivers support this output-variable hook; the async
        adapter also awaits the LOB reader returned by the converter.
        """
        return cursor.var(
            dialect.dbapi.CLOB,
            outconverter=lambda value: value.read(),
            arraysize=arraysize,
        )
