from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_csrf_protect.exceptions import CsrfProtectError
from fastapi.exceptions import RequestValidationError as PydanticError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core import resources
from src.common.errors.base import APPException
from src.common.errors.schemas import BaseErrorOut
from src.common.enums import MediaType
from src.core.logger import logger

from .response import APIResponse


def external_error_handler(request: Request, exc: APPException) -> JSONResponse:
    response_model = APIResponse.from_external_error(exc)
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=exc.status_code,
        media_type=MediaType.JSON
    )


def pydantic_error_handler(request: Request, exc: PydanticError) -> JSONResponse:
    response_model = APIResponse.from_pydantic_error(exc)
    return JSONResponse(
        # json mode: a rejected value is echoed back raw, and a Decimal
        # or a date would not survive json.dumps
        content=response_model.model_dump(mode="json", exclude_defaults=True),
        status_code=422,
        media_type=MediaType.JSON
    )


def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Answer Starlette's own HTTP errors in the app's error envelope.

    An unmatched path and a wrong method never reach a router, so they are the
    two failures that would otherwise reply in Starlette's ``{"detail": ...}``
    shape — and they are the two a client hits most while finding its way
    around the API.

    Args:
        request (Request): The incoming request.
        exc (StarletteHTTPException): The raised Starlette HTTP error.
    Returns:
        (JSONResponse): The error in the standard envelope.
    """
    codes = {
        404: resources.ROUTE_NOT_FOUND,
        405: resources.METHOD_NOT_ALLOWED,
    }
    response_model = APIResponse(
        success=False,
        error=BaseErrorOut(
            message=str(exc.detail),
            message_code=codes.get(exc.status_code, resources.SERVER_ERROR),
        ),
    )
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=exc.status_code,
        # a 405 without Allow, or a 401 without WWW-Authenticate, is not the
        # status it claims to be
        headers=exc.headers,
        media_type=MediaType.JSON
    )


def csrf_error_handler(request: Request, exc: CsrfProtectError) -> JSONResponse:
    response_model = APIResponse(
        success=False,
        error=BaseErrorOut(message=exc.message, message_code=resources.CSRF_FAILED),
    )
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=exc.status_code,
        media_type=MediaType.JSON
    )


def unexcepted_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(exc)
    response_model = APIResponse.get_server_error()
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=500,
        media_type=MediaType.JSON
    )

exception_handlers = {
    PydanticError: pydantic_error_handler,
    StarletteHTTPException: http_error_handler,
    APPException: external_error_handler,
    CsrfProtectError: csrf_error_handler,
    Exception: unexcepted_error_handler
}


def setup_exception_handlers(app: FastAPI) -> None:
    for exc_class, handler in exception_handlers.items():
        app.add_exception_handler(exc_class, handler)