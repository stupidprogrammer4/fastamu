"""HTTP auth and path dependencies — a self-contained, framework-level example.

In the original product this file was a thin adapter over the identity
modules' auth services. In the template it is deliberately module-free: it
ships a generic `Scope` enum plus a `require_access` dependency that validates
a bearer JWT and checks a `scopes` claim. Swap this for your own identity
module (bind an `IAuthService` and delegate to it) when you build one — every
router already depends only on the names exported here.
"""

from enum import StrEnum
from inspect import Parameter, Signature
from typing import Annotated, Callable

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.bases.encryption import IDEncryption
from src.common.errors.exceptions import (
    NotFoundException,
    UnAuthorizedException,
)
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
        # a real identity module would raise ForbiddenException with the caller
        # id here
        if scope.value not in principal.scopes:
            raise UnAuthorizedException(
                message=f"missing scope: {scope.value}",
                message_code=resources.INSUFFICIENT_SCOPE,
            )
        return principal

    return dependency


def decode_path_id(
    encryption: IDEncryption,
    entity: str,
    param: str = "id",
) -> Callable[..., int]:
    """Take the public id out of the path and hand the handler the real one.

    The inbound half of `BaseIDOutput`: the route keeps speaking public ids,
    the
    service keeps speaking row ids, and neither has to know about the other::

        OrderID = Annotated[int, Depends(decode_path_id(ORDER_IDS, "Order"))]

        @router.get("/{id}")
        async def get(id: OrderID, service: FromDishka[IOrderService]): ...

    A public id that does not decode is a 404, not a 400 — a forged id is
    indistinguishable from one that never existed, and saying which would turn
    the endpoint into an oracle for valid ids.

    Args:
        encryption (IDEncryption): The mapping the entity's ids were encoded
            with.
        entity (str): Entity name for the 404 body.
        param (str): The path parameter to read.
    Returns:
        (Callable[..., int]): A dependency returning the decoded row id.
    """

    def resolve(**path: int) -> int:
        public_id = path[param]
        internal = encryption.try_decode(public_id)
        if internal is None:
            raise NotFoundException(
                message=f"No {entity} with id '{public_id}'",
                message_code=resources.NOT_FOUND_ERROR,
                entity=entity,
                identifier="id",
                identifier_value=public_id,
            )
        return internal

    # FastAPI reads the signature to know which path param to inject; **path
    # alone would tell it nothing
    resolve.__signature__ = Signature(
        [Parameter(param, Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )
    return resolve
