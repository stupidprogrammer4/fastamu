from typing import Optional, Sequence, Union

from fastapi.exceptions import RequestValidationError as PydanticError
from pydantic import BaseModel

from fastamu.common.errors.base import APPException
from fastamu.common.errors.outputs import (
    BaseErrorOut,
    ValidationErrorOut,
    errors_types,
)
from fastamu.common.schemas.meta import BaseMeta
from fastamu.common.schemas.outputs import BaseOutput
from fastamu.core import resources

ErrorType = Union[*errors_types]


class APIResponse[TOut: BaseOutput | None, TMeta: BaseMeta | None](BaseModel):
    success: bool
    message_code: Optional[str] = None
    data: Optional[Union[TOut, Sequence[TOut]]] = None
    meta: Optional[TMeta] = None
    error: Optional[ErrorType] = None
    errors: Optional[Sequence[ErrorType]] = None

    @classmethod
    def from_data(
        cls,
        data: Union[TOut, Sequence[TOut]],
        message_code: Optional[str] = None,
        errors: Optional[Sequence[APPException]] = None,
    ):
        error_schemas = [e.as_schema() for e in errors] if errors else None
        return cls(
            success=True,
            data=data,
            message_code=message_code,
            errors=error_schemas,
        )

    @classmethod
    def from_external_error(cls, error: APPException):
        return cls(success=False, error=error.as_schema())

    @classmethod
    def from_pydantic_error(cls, error: PydanticError):
        errors = []
        for e in error.errors():
            errors.append(
                ValidationErrorOut(
                    message=e["msg"],
                    message_code=e["type"],
                    loc=e["loc"][1:] if e["loc"] else [],
                    ctx=e.get("ctx"),
                    input=e.get("input"),
                )
            )

        return APIResponse(success=False, errors=errors)

    @classmethod
    def get_server_error(cls):
        return cls(
            success=False,
            error=BaseErrorOut(
                message="Internal server error",
                message_code=resources.SERVER_ERROR,
            ),
        )
