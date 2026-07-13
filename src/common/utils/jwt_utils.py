"""
JWT encode/decode helpers.

Deliberately config-agnostic: callers pass the secret/algorithm/expiry
(wire them from `JWTConfig`). Keeps this layer pure and unit-testable, and
avoids a `common -> core.config` import cycle.

Decode failures surface as `UnAuthorizedException` so they flow through the
normal external-error handlers instead of leaking a raw `PyJWTError`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from src.common.errors.exceptions import UnAuthorizedException
from src.core import resources

DEFAULT_ALGORITHM = "HS256"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def create_token(
    subject: str,
    secret_key: str,
    *,
    expires_in: timedelta,
    token_type: TokenType = TokenType.ACCESS,
    algorithm: str = DEFAULT_ALGORITHM,
    extra_claims: Mapping[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_access_token(
    subject: str,
    secret_key: str,
    *,
    expires_minutes: int,
    algorithm: str = DEFAULT_ALGORITHM,
    extra_claims: Mapping[str, Any] | None = None,
) -> str:
    return create_token(
        subject,
        secret_key,
        expires_in=timedelta(minutes=expires_minutes),
        token_type=TokenType.ACCESS,
        algorithm=algorithm,
        extra_claims=extra_claims,
    )


def create_refresh_token(
    subject: str,
    secret_key: str,
    *,
    expires_minutes: int,
    algorithm: str = DEFAULT_ALGORITHM,
    extra_claims: Mapping[str, Any] | None = None,
) -> str:
    return create_token(
        subject,
        secret_key,
        expires_in=timedelta(minutes=expires_minutes),
        token_type=TokenType.REFRESH,
        algorithm=algorithm,
        extra_claims=extra_claims,
    )


def decode_token(
    token: str,
    secret_key: str,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
    expected_type: TokenType | None = None,
) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, secret_key, algorithms=[algorithm])
    except ExpiredSignatureError as exc:
        raise UnAuthorizedException(
            message="token has expired",
            message_code=resources.TOKEN_EXPIRED,
        ) from exc
    except InvalidTokenError as exc:
        raise UnAuthorizedException(
            message="invalid authentication token",
            message_code=resources.INVALID_TOKEN,
        ) from exc

    if expected_type is not None and payload.get("type") != expected_type.value:
        raise UnAuthorizedException(
            message=f"expected a {expected_type.value} token",
            message_code=resources.INVALID_TOKEN,
        )

    return payload
