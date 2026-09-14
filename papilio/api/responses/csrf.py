from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi_csrf_protect.exceptions import CsrfProtectError

from papilio.core import resources
from papilio.errors.outputs import BaseErrorOut
from papilio.types.enums import MediaType

from .envelope import APIResponse


async def csrf_error_handler(
    request: Request, exc: CsrfProtectError
) -> JSONResponse:
    response_model = APIResponse(
        success=False,
        error=BaseErrorOut(
            message=exc.message, message_code=resources.CSRF_FAILED
        ),
    )
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=exc.status_code,
        media_type=MediaType.JSON,
    )
