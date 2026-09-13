"""Native model defaults, SQL defaults and nullability are explicit."""

from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import Integer, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from papilio.infra.db.dialects.postgresql import ArrayField
from papilio.infra.db.fields import (
    BoolField,
    CharField,
    JSONField,
    TimestampField,
)
from papilio.infra.db.models import IdentifiedEntity, VersionEntity
from papilio.infra.db.table import BaseTable


class DefaultsModel(IdentifiedEntity):
    stamped: datetime | None = TimestampField(
        default=None, server_default=text("now()")
    )
    label: str | None = CharField(20, default=None, server_default="pending")
    active: bool = BoolField(default=False)
    optional: str | None = CharField(20, default=None, nullable=True)
    payload: dict = JSONField(default_factory=dict)


class DefaultsTable(DefaultsModel, BaseTable, table=True):
    __tablename__ = "tbl_column_default_probe"


def test_native_server_defaults_distinguish_sql_from_strings():
    ddl = str(
        CreateTable(DefaultsTable.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "DEFAULT now()" in ddl
    assert "DEFAULT 'pending'" in ddl


def test_explicit_python_defaults_do_not_enter_partial_rows():
    first = DefaultsModel()
    second = DefaultsModel()
    assert first.stamped is None
    assert first.label is None
    assert first.optional is None
    assert first.active is False
    assert first.payload == {}
    assert first.payload is not second.payload
    assert first.to_row() == {}


def test_nullable_and_server_default_do_not_make_model_fields_optional():
    class RequiredModel(IdentifiedEntity):
        optional_in_sql: str | None = CharField(20, nullable=True)
        supplied_by_sql: str = CharField(20, server_default="pending")

    with pytest.raises(ValidationError) as error:
        RequiredModel()
    assert {entry["loc"] for entry in error.value.errors()} == {
        ("optional_in_sql",),
        ("supplied_by_sql",),
    }


class ArrayDefaultsModel(IdentifiedEntity):
    callable_value: list[int] = ArrayField(
        Integer, default_factory=lambda: [7], server_default=text("ARRAY[9]")
    )
    constant_value: list[int] = ArrayField(
        Integer, default=[5], server_default=text("ARRAY[9]")
    )
    server_value: list[int] | None = ArrayField(
        Integer,
        default=None,
        server_default=text("ARRAY[9]"),
        gin_index="ix_array_defaults_server",
    )


class ArrayDefaultsTable(ArrayDefaultsModel, BaseTable, table=True):
    pass


def test_array_defaults_remain_explicit_and_independent():
    first = ArrayDefaultsModel()
    second = ArrayDefaultsModel()
    assert first.callable_value == [7]
    assert first.constant_value == [5]
    assert first.server_value is None
    first.callable_value.append(8)
    first.constant_value.append(6)
    assert second.callable_value == [7]
    assert second.constant_value == [5]
    assert "server_value" not in first.to_row()
    ddl = str(
        CreateTable(ArrayDefaultsTable.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert ddl.count("DEFAULT ARRAY[9]") == 3


def test_version_entity_does_not_install_an_implicit_update_expression():
    class VersionedTable(
        IdentifiedEntity, VersionEntity, BaseTable, table=True
    ):
        pass

    assert VersionedTable.__table__.c.version_num.onupdate is None


def test_array_gin_index_is_declared_with_its_column():
    index = next(iter(ArrayDefaultsTable.__table__.indexes))
    assert index.name == "ix_array_defaults_server"
    assert list(index.columns) == [ArrayDefaultsTable.__table__.c.server_value]
    assert index.dialect_options["postgresql"]["using"] == "gin"


@pytest.mark.parametrize("none_as_null", [False, True])
def test_oracle_json_type_preserves_the_requested_null_semantics(none_as_null):
    from sqlalchemy import JSON

    from papilio.infra.db.dialects.oracle import OracleJSON

    type_ = OracleJSON(none_as_null=none_as_null)
    assert type_.process_bind_param(None, None) == (
        None if none_as_null else "null"
    )
    assert type_.process_bind_param(JSON.NULL, None) == "null"
    assert type_.should_evaluate_none is not none_as_null
    assert type_.process_result_value("null", None) is None


def test_foreign_keys_computed_fields_and_scalar_helpers_declare_native_sql():
    from decimal import Decimal
    from enum import Enum

    from sqlalchemy import Boolean

    from papilio.infra.db.fields import (
        BigIntField,
        ComputedField,
        DateField,
        EnumField,
        FloatField,
        ForeignKeyField,
        NumericField,
        SmallIntField,
        TextField,
    )

    class State(str, Enum):
        ready = "ready"

    class ToolsTable(IdentifiedEntity, BaseTable, table=True):
        parent_id: int | None = ForeignKeyField(
            "tbl_column_default_probe.id",
            nullable=True,
            default=None,
            ondelete="SET NULL",
            index=True,
        )
        small: int = SmallIntField(default=1)
        big: int = BigIntField(default=1)
        ratio: float = FloatField(default=1.0)
        price: Decimal = NumericField(10, 2, default=Decimal("1.25"))
        day: str = DateField()
        state: State = EnumField(State, default=State.ready)
        description: str = TextField(default="")
        computed: bool | None = ComputedField(
            "small > 0", Boolean, default=None
        )

    columns = ToolsTable.__table__.c
    key = next(iter(columns.parent_id.foreign_keys))
    assert key.target_fullname == "tbl_column_default_probe.id"
    assert key.ondelete == "SET NULL"
    assert columns.parent_id.index
    assert str(columns.computed.computed.sqltext) == "small > 0"
    assert columns.price.type.precision == 10
    assert columns.price.type.scale == 2
    ddl = str(
        CreateTable(ToolsTable.__table__).compile(dialect=postgresql.dialect())
    )
    assert "ON DELETE SET NULL" in ddl
    assert "GENERATED ALWAYS AS" in ddl
