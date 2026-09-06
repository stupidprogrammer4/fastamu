"""`server_default` is SQL. These pin the consequence: an expression runs, and
a literal has to carry its own quotes."""

from datetime import datetime

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from fastamu.common.models.base import BaseIDModel
from fastamu.common.models.fields import (
    BoolField,
    CharField,
    JSONField,
    TimestampField,
)
from fastamu.infra.db.table import BaseTable


class DefaultsModel(BaseIDModel):
    stamped: datetime = TimestampField(server_default="now()")
    label: str = CharField(20, server_default="'pending'")
    bare_label: str = CharField(20, server_default="pending")
    active: bool = BoolField(default=False)
    optional: str | None = CharField(20, nullable=True)
    payload: dict = JSONField(default=dict)


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


def test_a_bare_string_default_is_a_literal_for_string_fields() -> None:
    assert "bare_label VARCHAR(20) DEFAULT 'pending'" in ddl()


def test_database_defaults_and_nullable_fields_are_optional_to_models() -> (
    None
):
    model = DefaultsModel()

    assert model.stamped is None
    assert model.label is None
    assert model.bare_label is None
    assert model.optional is None


def test_python_defaults_are_available_before_persistence() -> None:
    first = DefaultsModel()
    second = DefaultsModel()

    assert first.active is False
    assert first.payload == {}
    assert first.payload is not second.payload
