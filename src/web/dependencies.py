"""HTTP auth dependencies — a self-contained, framework-level example.

In the original product this file was a thin adapter over the identity
modules' auth services. In the template it is deliberately module-free: it
ships a generic `Scope` enum plus a `require_access` dependency that validates
a bearer JWT and checks a `scopes` claim. Swap this for your own identity
module (bind an `IAuthService` and delegate to it) when you build one — every
router already depends only on the names exported here.
"""

from enum import StrEnum
from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.errors.exceptions import UnAuthorizedException
from src.common.utils import jwt_utils
from src.core import resources
from src.core.config import Settings

bearer = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


class Scope(StrEnum):
    """Guardable sections of the API — one per feature module.

    The demo modules reference these; extend the enum as you add modules
    (the module scaffolder does not touch it — scopes are an app concern).
    """

    BRANDS = "brands"
    STORAGE = "storage"
    SYSTEM = "system"
    JOBS = "jobs"


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
    payload = jwt_utils.decode_token(
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


def require_access(scope: Scope):
    """Build a dependency that requires the caller to hold ``scope``.

    Args:
        scope (Scope): The scope the route is guarded by.
    Returns:
        (Callable): A FastAPI dependency yielding the authorized `Principal`.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        # a real identity module would raise ForbiddenException with the caller id here
        if scope.value not in principal.scopes:
            raise UnAuthorizedException(
                message=f"missing scope: {scope.value}",
                message_code=resources.INSUFFICIENT_SCOPE,
            )
        return principal

    return dependency
