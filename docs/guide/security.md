# Authentication, identifiers and rate limits

Papilio supplies security primitives and HTTP dependencies. Your application owns user lookup, credential verification, permission policy, token rotation and revocation. A generated CRUD module does not automatically require authentication.

## Hash passwords asynchronously

`CoreProvider` supplies an application-scoped `PasswordHasher`, configured with `crypto.password_salt` as its pepper:

```python
from papilio.security.passwords import PasswordHasher

hasher = PasswordHasher(pepper="application-secret")
hashed = await hasher.hash("example-password")
assert await hasher.verify("example-password", hashed)
```

Hashing runs in a worker thread. Store the hash, keep the pepper stable and private, and inject the shared hasher into your identity service. The synchronous primitives also exist, but should not be called directly in an async request path for expensive hashing.

## Issue and decode a token

After your application has authenticated a user:

```python
from papilio.security.tokens import (
    TokenType,
    create_access_token,
    decode_token,
)

token = create_access_token(
    subject="42",
    secret_key=settings.jwt.secret_key,
    expires_minutes=settings.jwt.access_token_expire_minutes,
    algorithm=settings.jwt.algorithm,
    extra_claims={"scopes": ["products:read"]},
)
payload = decode_token(
    token,
    settings.jwt.secret_key,
    algorithm=settings.jwt.algorithm,
    expected_type=TokenType.ACCESS,
)
```

Extra claims can overwrite existing claims in the current helper; do not pass an untrusted request dictionary. `decode_token` checks the requested token type only when `expected_type` is provided. Supply `audience` when your application uses an audience claim.

## Built-in principal and scopes

```python
from fastapi import APIRouter, Depends
from papilio.api.authentication import CurrentPrincipal, require_access

router = APIRouter()


@router.get("/me")
async def me(principal: CurrentPrincipal):
    return {"subject": principal.subject, "scopes": sorted(principal.scopes)}


@router.get("/protected", dependencies=[Depends(require_access("products:read"))])
async def protected():
    return {"allowed": True}
```

Register the router in a Papilio app so the Settings dependency is available. `Principal` contains a subject and a frozen set of scopes.

The current built-in principal decoder does **not** pass `expected_type=ACCESS`; it should not be assumed to reject a refresh token signed with the same key. If both token types are used, define an authentication dependency using explicit type validation, as above. The built-in scope guard currently returns 401 for a missing scope. Use your own dependency with `ForbiddenException` when your policy requires 403.

## Public identifiers

`IDEncryption` and `BaseIDOutput` provide encoded public IDs. `decode_path_id(encryption, entity, param="id")` builds a dependency for path decoding; decoding failure becomes 404. Encoding an ID does not authorize access to its entity. Refer to the [security signatures](../reference/utilities.md) for key construction and encryption methods before enabling this feature.

## Configure rate limiting

Install `rate-limit`, configure Redis, and register `RedisProvider(settings.redis)`. Add to your full configuration:

```yaml
rate_limit:
  enabled: true
  trusted_proxies: []
  general:
    limit: 120
    window_seconds: 60
  rules:
    login:
      limit: 5
      window_seconds: 300
```

Attach a named dependency to a route:

```python
from papilio.api.rate_limit.dependencies import by_body_field, by_ip, rate_limit

login_limit = rate_limit(
    "login",
    parts=(by_ip, by_body_field("email")),
    closed_when_down=True,
)


@router.post("/login", dependencies=[login_limit])
async def login():
    return {"next": "Implement credential verification here"}
```

Each key part charges an **independent** bucket; this is not a combined IP-and-email key. A missing named rule or disabled rate-limit config skips that guard. The general limiter fails open when its Redis store is unavailable. Named guards can fail closed with `closed_when_down=True`.

Only explicitly trusted proxy peers allow `X-Forwarded-For` to affect the client key. If you replace the default middleware list, add `RateLimitMiddleware` yourself to keep the general limiter. Named route dependencies remain separate.

[Authentication and rate-limit signatures](../reference/api.md)
