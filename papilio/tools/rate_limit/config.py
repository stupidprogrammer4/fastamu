from pydantic import BaseModel, Field


class RateLimitRule(BaseModel):
    """One budget: `limit` calls per `window_seconds`."""

    limit: int = Field(gt=0)
    window_seconds: int = Field(gt=0)


class RateLimitConfig(BaseModel):
    """The rate-limit budgets, all of them tunable without a deploy.

    `general` is the blanket rule the middleware applies to every request;
    `rules` are the named ones a route asks for by name via
    `rate_limit("login")` — a route whose name is missing here is simply not
    limited, so a rule can be dropped from the config to turn it off.

    `trusted_proxies` lists the peers whose ``X-Forwarded-For`` may be
    believed. Leave it empty when nothing sits in front of the app: an unvetted
    header is a free way to spoof a fresh bucket per call."""

    enabled: bool = False
    trusted_proxies: list[str] = Field(default_factory=list)
    general: RateLimitRule = RateLimitRule(limit=120, window_seconds=60)
    rules: dict[str, RateLimitRule] = Field(default_factory=dict)
