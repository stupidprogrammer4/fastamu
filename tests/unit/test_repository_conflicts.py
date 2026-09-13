"""Driver-specific unique-error decoding remains an explicit dialect tool."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from fastamu.infra.db.dialects.postgresql import PostgreSQLDialect


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("Key (code)=(abc) already exists.", {"code": "abc"}),
        (
            "Key (code, tenant_id)=(abc, 3) already exists.",
            {"code": "abc", "tenant_id": "3"},
        ),
        ("unknown localized detail", {}),
    ],
)
def test_unique_violation_details(detail, expected):
    cause = SimpleNamespace(sqlstate="23505", detail=detail)
    error = IntegrityError("stmt", {}, SimpleNamespace(__cause__=cause))
    assert PostgreSQLDialect().unique_values(error) == expected


@pytest.mark.parametrize("sqlstate", ["23503", "23514", None])
def test_other_integrity_errors_are_not_unique_conflicts(sqlstate):
    cause = SimpleNamespace(sqlstate=sqlstate, detail="not a unique error")
    error = IntegrityError("stmt", {}, SimpleNamespace(__cause__=cause))
    assert PostgreSQLDialect().unique_values(error) is None
