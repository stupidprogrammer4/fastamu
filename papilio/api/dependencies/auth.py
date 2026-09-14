"""Opt-in bearer extraction. The application supplies authentication logic."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from papilio.core import resources
from papilio.errors.exceptions import UnAuthorizedException


class Scoped(Protocol):
    @property
    def scopes(self) -> frozenset[str]: ...


def bearer[T](
    authenticate: Callable[[str], Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    async def resolve(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(HTTPBearer(auto_error=False)),
        ],
    ) -> T:
        if credentials is None:
            raise UnAuthorizedException(
                message="missing authentication token",
                message_code=resources.MISSING_TOKEN,
            )
        return await authenticate(credentials.credentials)

    return resolve


def require_access[T: Scoped](
    principal: Callable[..., Awaitable[T]], scope: str
) -> Callable[..., Awaitable[T]]:
    """Optional scopes, independent of JWT and the identity model."""

    async def resolve(caller: T = Depends(principal)) -> T:
        if scope not in caller.scopes:
            raise UnAuthorizedException(
                message=f"missing scope: {scope}",
                message_code=resources.INSUFFICIENT_SCOPE,
            )
        return caller

    return resolve
