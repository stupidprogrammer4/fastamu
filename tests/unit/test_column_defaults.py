"""`server_default` is SQL. These pin the consequence: an expression runs, and
a literal has to carry its own quotes."""

from datetime import datetime

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from src.infra.postgres.models.base import BaseIDModel
from src.infra.postgres.types import CharField, TimestampField


class DefaultsModel(BaseIDModel, table=True):
    __tablename__ = "tbl_column_default_probe"

    stamped: datetime = TimestampField(server_default="now()")
    label: str = CharField(20, server_default="'pending'")


def ddl() -> str:
    return str(
        CreateTable(DefaultsModel.__table__).compile(
            dialect=postgresql.dialect()
        )
    )


def test_an_expression_reaches_postgres_as_sql() -> None:
    # not DEFAULT 'now()', which would default the column to seven characters
    assert "DEFAULT now()" in ddl()


def test_a_quoted_literal_stays_a_literal() -> None:
    assert "DEFAULT 'pending'" in ddl()
