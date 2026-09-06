"""A unique index is a rule the client broke, so it must read as a 409 naming
the fields — not the 500 an untranslated IntegrityError becomes."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from fastamu.common.errors.exceptions import ConflictException
from fastamu.common.models.base import BaseIDModel
from fastamu.infra.db.repository import DBIDRepository


class WidgetModel(BaseIDModel):
    code: str = ""


class WidgetRepository(DBIDRepository[WidgetModel]):
    def __init__(self) -> None:  # no unit of work; only the translation here
        from fastamu.infra.db.dialects.postgresql import PostgreSQLDialect

        self.dialect = PostgreSQLDialect()


def integrity_error(sqlstate: str, detail: str) -> IntegrityError:
    cause = SimpleNamespace(sqlstate=sqlstate, detail=detail)
    orig = SimpleNamespace(__cause__=cause)
    return IntegrityError("stmt", {}, orig)  # type: ignore[arg-type]


def test_a_unique_violation_names_the_fields_that_collided() -> None:
    repo = WidgetRepository()
    error = integrity_error("23505", "Key (code)=(abc) already exists.")

    conflict = repo._as_conflict(error)

    assert isinstance(conflict, ConflictException)
    assert conflict.status_code == 409
    assert conflict.unique_dict == {"code": "abc"}
    assert conflict.message_code == "widget_confilict_error"


def test_a_composite_index_names_every_column() -> None:
    repo = WidgetRepository()
    error = integrity_error(
        "23505", "Key (code, tenant_id)=(abc, 3) already exists."
    )

    conflict = repo._as_conflict(error)

    assert conflict is not None
    assert conflict.unique_dict == {"code": "abc", "tenant_id": "3"}


def test_an_unparsable_detail_still_answers_409() -> None:
    # a different locale or a future wording loses the detail, not the status
    repo = WidgetRepository()
    error = integrity_error("23505", "something we have never seen")

    conflict = repo._as_conflict(error)

    assert conflict is not None
    assert conflict.unique_dict == {}


@pytest.mark.parametrize("sqlstate", ["23503", "23514", None])
def test_any_other_violation_is_left_to_raise(sqlstate) -> None:
    # a foreign key or check violation is the caller's bug, not a duplicate the
    # client can fix by changing a field
    repo = WidgetRepository()
    error = integrity_error(sqlstate, "Key (code)=(abc) already exists.")

    assert repo._as_conflict(error) is None
