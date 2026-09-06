import json
from typing import Any

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
        return None if value is None else json.dumps(value)

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)
