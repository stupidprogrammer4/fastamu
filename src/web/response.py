from pydantic import BaseModel
from fastapi.exceptions import RequestValidationError as PydanticError

from typing import Union, Optional, TypeVar, Generic, Sequence

from src.core import resources
from src.common.bases.schemas import BaseOutput, BaseMeta
from src.common.errors.schemas import errors_types, ValidationErrorOut, BaseErrorOut
from src.common.errors.base import APPException

ErrorType = Union[*errors_types]

O = TypeVar('O', bound=BaseOutput | None)
M = TypeVar('M', bound=BaseMeta | None)
E = TypeVar('E', bound=APPException)

class APIResponse(BaseModel, Generic[O, M]):
    success: bool
    message_code: Optional[str] = None
    data: Optional[Union[O, Sequence[O]]] = None
    meta: Optional[M] = None
    error: Optional[ErrorType] = None
    errors: Optional[Sequence[ErrorType]] = None

    @classmethod
    def from_data(
        cls,
        data: Union[O, Sequence[O]],
        message_code: Optional[str] = None,
        errors: Optional[Sequence[E]] = None,
    ):
        error_schemas = [e.as_schema() for e in errors] if errors else None
        return cls(
            success=True,
            data=data,
            message_code=message_code,
            errors=error_schemas
        )

    
    @classmethod
    def from_external_error(
        cls,
        error: APPException
    ):
        return cls(
            success=False,
            error=error.as_schema()
        )

    
    @classmethod
    def from_pydantic_error(
        cls,
        error: PydanticError
    ):
        errors = []
        for e in error.errors():
            errors.append(
                ValidationErrorOut(
                    message=e['msg'],
                    message_code=e['type'],
                    loc=e['loc'][1:] if e['loc'] else [],
                    ctx=e.get('ctx'),
                    input=e.get('input')
                )
            )

        return APIResponse(
            success=False,
            errors=errors
        )
    
    @classmethod
    def get_server_error(cls):
        return cls(
            success=False,
            error=BaseErrorOut(
                message="Internal server error",
                message_code=resources.SERVER_ERROR
            )
        )