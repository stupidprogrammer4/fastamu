from typing import Any

import orjson
from sqlalchemy import Text
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

    def process_bind_param(self, value, dialect):
        return None if value is None else orjson.dumps(value).decode("utf-8")

    def process_result_value(self, value, dialect):
        return None if value is None else orjson.loads(value)
