"""`server_default` is SQL. These pin the consequence: an expression runs, and
a literal has to carry its own quotes."""

from datetime import datetime

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from fastamu.common.bases.fields import CharField, TimestampField
from fastamu.common.bases.models import BaseIDModel
from fastamu.infra.postgres.models.base import BaseTable


class DefaultsModel(BaseIDModel):
    stamped: datetime = TimestampField(server_default="now()")
    label: str = CharField(20, server_default="'pending'")


class DefaultsTable(DefaultsModel, BaseTable, table=True):
    __tablename__ = "tbl_column_default_probe"


def ddl() -> str:
    return str(
        CreateTable(DefaultsTable.__table__).compile(
            dialect=postgresql.dialect()
        )
    )


def test_an_expression_reaches_postgres_as_sql() -> None:
    # not DEFAULT 'now()', which would default the column to seven characters
    assert "DEFAULT now()" in ddl()


def test_a_quoted_literal_stays_a_literal() -> None:
    assert "DEFAULT 'pending'" in ddl()
