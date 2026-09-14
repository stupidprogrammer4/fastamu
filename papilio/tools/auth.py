"""Optional JWT authenticator; applications can supply their own."""

from dataclasses import dataclass

from papilio.core import resources
from papilio.errors.exceptions import UnAuthorizedException
from papilio.security.tokens import TokenType, decode_token


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]


class JWTAuth:
    def __init__(
        self,
        secret_key: str,
        *,
        algorithm: str = "HS256",
        audience: str | None = None,
    ) -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.audience = audience

    async def authenticate(self, token: str) -> Principal:
        payload = decode_token(
            token,
            self.secret_key,
            algorithm=self.algorithm,
            expected_type=TokenType.ACCESS,
            audience=self.audience,
        )
        subject = payload.get("sub")
        scopes = payload.get("scopes", [])
        if not isinstance(subject, str) or not subject:
            raise UnAuthorizedException(
                message="missing token subject",
                message_code=resources.INVALID_TOKEN,
            )
        if not isinstance(scopes, list) or any(
            not isinstance(scope, str) for scope in scopes
        ):
            raise UnAuthorizedException(
                message="invalid token scopes",
                message_code=resources.INVALID_TOKEN,
            )
        return Principal(subject, frozenset(scopes))
