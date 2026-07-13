from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel


class BaseErrorOut(BaseModel):
    message_code: str
    message: str


class ValidationErrorOut(BaseErrorOut):
    loc: Sequence[Any]
    input: Any | None = None
    ctx: dict[str, Any] | None = None
    errors: Sequence[ValidationErrorOut] | None = None


class NotFoundErrorOut(BaseErrorOut):
    entity: str
    identifier: str
    identifier_value: str


class ForbiddenErrorOut(BaseErrorOut):
    user_id: int


class UnAuthorizedErrorOut(BaseErrorOut):
    pass


class ConflictErrorOut(BaseErrorOut):
    unique_dict: dict[str, Any]


errors_types = [
    BaseErrorOut,
    ValidationErrorOut,
    NotFoundErrorOut,
    ForbiddenErrorOut,
    UnAuthorizedErrorOut,
    ConflictErrorOut,
]
