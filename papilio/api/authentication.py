"""Bearer authentication and scope checks for HTTP routes."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from papilio.core import resources
from papilio.core.config import Settings
from papilio.errors.exceptions import UnAuthorizedException
from papilio.security import tokens

bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


class Principal:
    """The authenticated caller decoded from the token.

    Args:
        subject (str): The token subject (``sub`` claim).
        scopes (frozenset[str]): Scopes the caller is allowed to access.
    """

    def __init__(self, subject: str, scopes: frozenset[str]) -> None:
        self.subject = subject
        self.scopes = scopes


@inject
async def get_current_principal(
    credentials: Credentials,
    settings: FromDishka[Settings],
) -> Principal:
    """Decode + validate the bearer token into a `Principal`.

    Args:
        credentials (Credentials): The optional bearer credentials.
        settings (Settings): App settings (holds the JWT secret/algorithm).
    Returns:
        (Principal): The authenticated caller.
    """
    token = credentials.credentials if credentials else None
    if token is None:
        raise UnAuthorizedException(
            message="missing authentication token",
            message_code=resources.MISSING_TOKEN,
        )
    payload = tokens.decode_token(
        token,
        settings.jwt.secret_key,
        algorithm=settings.jwt.algorithm,
    )
    principal = Principal(
        subject=str(payload.get("sub", "")),
        scopes=frozenset(payload.get("scopes", [])),
    )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_access(scope: str):
    """Build a dependency that requires the caller to hold ``scope``.

    Args:
        scope (Scope): The scope the route is guarded by.
    Returns:
        (Callable): A FastAPI dependency yielding the authorized `Principal`.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        # a real identity module would raise ForbiddenException with the caller
        # id here
        if scope not in principal.scopes:
            raise UnAuthorizedException(
                message=f"missing scope: {scope}",
                message_code=resources.INSUFFICIENT_SCOPE,
            )
        return principal

    return dependency
