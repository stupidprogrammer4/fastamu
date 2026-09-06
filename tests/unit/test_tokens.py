from datetime import timedelta

import pytest

from fastamu.common.errors.exceptions import UnAuthorizedException
from fastamu.common.security.tokens import create_token, decode_token


def test_decode_can_require_the_intended_audience() -> None:
    token = create_token(
        "1",
        "secret",
        expires_in=timedelta(minutes=1),
        extra_claims={"aud": "panel"},
    )

    assert decode_token(token, "secret", audience="panel")["sub"] == "1"
    with pytest.raises(UnAuthorizedException):
        decode_token(token, "secret", audience="shop")
